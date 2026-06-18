"""
Generator: raw_compliance — NALA internal compliance operations.

Internal source of record: risk scores (one+ per customer), compliance cases
(raised from KYC/AML/crypto signals), SARs (filed for the riskiest cases), and
the sanctions_list lookup. This is OUR system, so timestamps are clean tz-aware
datetimes (passed as Python datetimes -> timestamptz). National ids are governed
(national_id + national_id_hash).
"""
from __future__ import annotations

import datetime as dt
import hashlib
import json
import uuid as uuidlib

from common import (
    connect, ensure_schema, apply_ddl_file, truncate, bulk_copy,
    customer_master, rng, rand_datetime, det_uuid, maybe_null, N,
)

SCHEMA = "raw_compliance"
DDL = "sql/ddl/raw_compliance.sql"

REGULATORS = ["FCA", "FINTRAC", "FinCEN", "CBN", "BoU"]
ACTIVITY = ["structuring", "rapid_movement", "sanctions_hit", "third_party",
            "fraud", "mule_account"]
SANCTIONS_LISTS = ["OFAC SDN", "UN Consolidated", "UK HMT", "EU Consolidated"]
SANCTIONS_PROGRAMS = ["SDGT", "UKRAINE-EO13662", "IRAN", "DPRK", "RUSSIA-EO14024",
                      "SYRIA", "CYBER2"]


def _sha256(s: str) -> str:
    return hashlib.sha256(s.encode()).hexdigest()


def _national_id(r) -> str:
    return "".join(r.choice("0123456789") for _ in range(9))


def main(conn):
    ensure_schema(conn, SCHEMA)
    apply_ddl_file(conn, DDL)
    truncate(conn, f"{SCHEMA}.sars", f"{SCHEMA}.case_management",
             f"{SCHEMA}.risk_scores", f"{SCHEMA}.sanctions_list")

    customers = customer_master()
    risk_scores, cases, sars = [], [], []
    rs_seq, case_seq, sar_seq = 0, 0, 0

    for cust in customers:
        r = rng("compliance", cust.cid)
        cust_uuid = cust.uuid

        # ---- risk scores: 1, sometimes a re-score history of 2-3 ----
        n_scores = 1 + (r.randint(1, 2) if r.random() < 0.25 else 0)
        first_scored = rand_datetime(r, start=dt.date(2020, 1, 1))
        for si in range(n_scores):
            rs_seq += 1
            band_roll = r.random()
            if band_roll < 0.62:
                score, band = r.randint(0, 33), "low"
            elif band_roll < 0.90:
                score, band = r.randint(34, 66), "medium"
            elif band_roll < 0.985:
                score, band = r.randint(67, 89), "high"
            else:
                score, band = r.randint(90, 100), "prohibited"
            scored_at = first_scored + dt.timedelta(days=si * r.randint(30, 200))
            # messy: occasionally >1 row marked current (SCD bug)
            is_current = (si == n_scores - 1) or (r.random() < 0.04)
            risk_scores.append((
                rs_seq, cust.code, cust_uuid, score, band,
                r.choice(["crs-v1.0", "crs-v2.1", "crs-v2.3", "crs-v3.0"]),
                json.dumps({"geography": round(r.uniform(0, 1), 2),
                            "pep": round(r.uniform(0, 1), 2),
                            "adverse_media": round(r.uniform(0, 1), 2),
                            "velocity": round(r.uniform(0, 1), 2),
                            "product": round(r.uniform(0, 1), 2)}),
                r.random() < 0.03,                          # pep_flag
                band == "prohibited" and r.random() < 0.5,  # sanctions_flag
                r.random() < 0.05,                          # adverse_media_flag
                r.random() < 0.20,                          # high_risk_country
                is_current,
                scored_at,
                scored_at,
            ))

        # ---- cases: higher-risk customers get one (sometimes more) ----
        case_prob = {"low": 0.04, "medium": 0.15, "high": 0.7, "prohibited": 1.0}[band]
        if r.random() < case_prob:
            n_cases = 1 + (1 if r.random() < 0.2 else 0)
            for ci in range(n_cases):
                case_seq += 1
                opened = rand_datetime(r, start=first_scored.date())
                source = r.choice(["onfido", "complyadvantage", "chainalysis",
                                   "rules_engine", "manual"])
                source_ref = {
                    "onfido": "chk_" + det_uuid(("onfido_chk", cust.cid, 0)),
                    "complyadvantage": str(700_000_000 + cust.cid),
                    "chainalysis": "scr_" + det_uuid(("chain_scr", ("cust", cust.cid, 0))),
                }.get(source)
                ctype = {"onfido": "kyc_review", "complyadvantage": "aml_alert",
                         "chainalysis": "sanctions_review", "rules_engine":
                         "transaction_monitoring", "manual": "edd"}[source]
                status = r.choices(
                    ["open", "in_progress", "pending_info", "escalated", "closed"],
                    weights=[8, 12, 8, 7, 65])[0]
                if opened.year <= 2021 and status == "open" and r.random() < 0.3:
                    status = "NEW"                          # legacy value
                closed = (opened + dt.timedelta(days=r.randint(1, 45))
                          if status == "closed" else None)
                resolution = (r.choices(
                    ["cleared", "sar_filed", "account_closed", "false_positive", "escalated"],
                    weights=[55, 8, 7, 25, 5])[0] if status == "closed" else None)
                sla_due = opened + dt.timedelta(days=r.choice([3, 5, 10, 30]))
                cases.append((
                    case_seq, f"CASE-{opened.year}-{case_seq:06d}",
                    cust.code, ctype, source, source_ref, status,
                    r.choices(["low", "medium", "high", "critical"],
                              weights=[30, 40, 25, 5])[0],
                    maybe_null(f"analyst_{r.randint(1,12)}", 0.15 if status != "open" else 0.5, r),
                    r.choice(["l1_triage", "l2_investigation", "mlro"]),
                    band if band != "prohibited" else "high",
                    resolution, sla_due, opened, closed,
                    (closed is not None and closed > sla_due) if closed else (
                        dt.datetime.now() > sla_due.replace(tzinfo=None) if status != "closed" else False),
                    json.dumps([{"at": opened.isoformat(), "by": "system",
                                 "note": "case opened from " + source}]),
                    opened,
                ))

                # ---- SAR: filed for the worst resolutions ----
                if resolution in ("sar_filed", "account_closed") or band == "prohibited":
                    if r.random() < 0.8:
                        sar_seq += 1
                        nid = _national_id(r)
                        sar_status = r.choices(
                            ["draft", "filed", "acknowledged", "closed_no_action"],
                            weights=[10, 25, 45, 20])[0]
                        if opened.year <= 2021 and sar_status == "filed" and r.random() < 0.3:
                            sar_status = "SUBMITTED"        # legacy value
                        filed_at = (opened + dt.timedelta(days=r.randint(1, 30))
                                    if sar_status not in ("draft",) else None)
                        # references a transfer that triggered it (sparse)
                        tref = None
                        if r.random() < 0.6:
                            tidx = r.randrange(max(1, N["transfers"]))
                            tref = det_uuid(("transfer", tidx))
                        sars.append((
                            sar_seq, f"SAR-{opened.year}-{sar_seq:06d}",
                            cust.code, cust_uuid,
                            f"{cust.first} {cust.last}",
                            nid, _sha256(nid),              # governed national id
                            tref,
                            r.choice(ACTIVITY),
                            sar_status,
                            r.choices(["low", "medium", "high", "critical"],
                                      weights=[10, 30, 45, 15])[0],
                            r.choice(REGULATORS),
                            maybe_null(f"FIU-{r.randint(100000,999999)}", 0.4, r)
                            if sar_status in ("acknowledged", "closed_no_action") else None,
                            f"Subject linked to {r.choice(ACTIVITY)} pattern across "
                            f"{r.randint(2, 30)} transactions; escalated by {source}.",
                            round(r.uniform(1000, 500000), 2),
                            f"mlro_{r.randint(1,4)}",
                            filed_at, opened,
                            filed_at or opened,
                        ))

    # ---- sanctions_list lookup ----
    sanctions = []
    n_sanctions = 400
    fr = rng("sanctions_list")
    for i in range(n_sanctions):
        is_indiv = fr.random() < 0.7
        sanctions.append((
            i + 1,
            fr.choice(SANCTIONS_LISTS),
            f"{'INDIVIDUAL' if is_indiv else 'ENTITY'} {fr.randint(1000,9999)} "
            f"{fr.choice(['Holdings','Trading','al-','Group','LLC','Ltd'])}",
            "individual" if is_indiv else fr.choice(["entity", "vessel", "aircraft"]),
            json.dumps([f"alias-{fr.randint(1,99)}" for _ in range(fr.randint(0, 3))]),
            fr.choice(SANCTIONS_PROGRAMS),
            maybe_null(fr.choice(["RU", "IR", "KP", "SY", "VE", "CU"]), 0.3, fr),
            maybe_null(dt.date(fr.randint(1950, 1995), fr.randint(1, 12),
                               fr.randint(1, 28)), 0.5, fr) if is_indiv else None,
            dt.date(fr.randint(2014, 2026), fr.randint(1, 12), fr.randint(1, 28)),
            fr.random() < 0.92,
            f"https://sanctions.example/{fr.choice(SANCTIONS_LISTS).replace(' ','_')}/{i+1}",
            dt.datetime(2026, 1, 1),
        ))

    bulk_copy(conn, f"{SCHEMA}.risk_scores",
              ["id", "customer_code", "customer_uuid", "score", "risk_band",
               "model_version", "factors", "pep_flag", "sanctions_flag",
               "adverse_media_flag", "high_risk_country", "is_current",
               "scored_at", "created_at"], risk_scores)
    bulk_copy(conn, f"{SCHEMA}.case_management",
              ["case_id", "case_ref", "customer_code", "case_type", "source",
               "source_ref", "status", "priority", "assigned_to", "queue",
               "risk_rating", "resolution", "sla_due_at", "opened_at", "closed_at",
               "sla_breached", "notes", "created_at"], cases)
    bulk_copy(conn, f"{SCHEMA}.sars",
              ["sar_id", "sar_ref", "customer_code", "customer_uuid", "subject_name",
               "subject_national_id", "subject_national_id_hash", "transfer_id",
               "activity_type", "status", "priority", "regulator", "filing_reference",
               "narrative", "amount_usd", "filed_by", "filed_at", "created_at",
               "updated_at"], sars)
    bulk_copy(conn, f"{SCHEMA}.sanctions_list",
              ["entry_id", "list_name", "entity_name", "entity_type", "aliases",
               "program", "nationality", "dob", "listed_on", "is_active",
               "source_url", "created_at"], sanctions)

    print(f"[{SCHEMA}] risk_scores={len(risk_scores)} cases={len(cases)} "
          f"sars={len(sars)} sanctions_list={len(sanctions)}")


if __name__ == "__main__":
    c = connect()
    main(c)
    c.close()
