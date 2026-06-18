"""
Generator: raw_onfido — Onfido identity-verification (KYC) data.

Each NALA customer becomes one Onfido applicant (1:1). A subset of applicants
have additional re-verification checks. Each check carries 1-3 reports; document
+ facial_similarity + watchlist report variants are split into their own tables.

PII governance shown: document numbers stored as last4 + sha256 hash only.
"""
from __future__ import annotations

import datetime as dt
import hashlib
import json

from common import (
    connect, ensure_schema, apply_ddl_file, truncate, bulk_copy,
    customer_master, rng, rand_datetime, det_uuid,
    maybe_null, dirty_email, dirty_phone, ts_isoz, ts_epoch_s, N,
)

SCHEMA = "raw_onfido"
DDL = "sql/ddl/raw_onfido.sql"

DOC_TYPES = ["passport", "driving_licence", "national_identity_card", "residence_permit"]
ISO3 = {"GB": "GBR", "US": "USA", "IE": "IRL", "FR": "FRA", "DE": "DEU", "ES": "ESP",
        "IT": "ITA", "NL": "NLD", "BE": "BEL", "PT": "PRT", "AT": "AUT", "FI": "FIN",
        "GR": "GRC", "LU": "LUX", "MT": "MLT", "CY": "CYP", "EE": "EST", "LV": "LVA",
        "LT": "LTU", "SK": "SVK", "SI": "SVN"}
WATCHLIST_SOURCES = ["OFAC SDN", "UN Consolidated", "UK HMT", "EU Consolidated",
                     "Interpol Red Notices", "World-Check PEP"]


def _sha256(s: str) -> str:
    return hashlib.sha256(s.encode()).hexdigest()


def _doc_number(r) -> str:
    return "".join(r.choice("0123456789") for _ in range(9))


def main(conn):
    ensure_schema(conn, SCHEMA)
    apply_ddl_file(conn, DDL)
    truncate(conn,
             f"{SCHEMA}.applicants", f"{SCHEMA}.checks", f"{SCHEMA}.reports",
             f"{SCHEMA}.documents", f"{SCHEMA}.facial_similarity_reports",
             f"{SCHEMA}.watchlist_reports")

    customers = customer_master()

    applicants, checks, reports = [], [], []
    documents, facial, watchlist = [], [], []

    for cust in customers:
        r = rng("onfido", cust.cid)
        applicant_id = "applicant_" + det_uuid(("onfido_app", cust.cid))
        created = rand_datetime(r, start=dt.date(2019, 1, 1))

        # external_id is the customer code, but ~10% of legacy applicants lost it.
        ext = maybe_null(cust.code, 0.10, r)
        applicants.append((
            applicant_id,
            ext,
            maybe_null(cust.uuid, 0.45, r),                  # uuid only on newer rows
            cust.first,
            maybe_null(cust.last, 0.03, r),
            dirty_email(maybe_null(cust.email, 0.05, r), r),
            cust.dob,
            cust.street,
            cust.city,
            cust.postcode,
            cust.country,
            dirty_phone(maybe_null(cust.phone, 0.15, r), r),
            json.dumps([{"type": "national_identity_number",
                         "value_last4": _doc_number(r)[-4:]}]) if r.random() < 0.4 else None,
            ts_isoz(created),
            f"https://api.onfido.com/v3/applicants/{applicant_id}",
            r.random() < 0.02,                                # 2% sandbox
            r.random() < 0.01,                                # 1% soft-deleted (is_deleted)
            None,                                             # deleted_at
        ))

        # 1 onboarding check, plus occasional re-verification checks.
        n_checks = 1 + (1 if r.random() < 0.18 else 0)
        for ci in range(n_checks):
            chk_id = "chk_" + det_uuid(("onfido_chk", cust.cid, ci))
            chk_created = rand_datetime(r, start=created.date()) if ci else created
            # outcome distribution
            roll = r.random()
            if roll < 0.86:
                chk_status, chk_result = "complete", "clear"
            elif roll < 0.96:
                chk_status, chk_result = "complete", "consider"
            elif roll < 0.985:
                chk_status, chk_result = "withdrawn", None
            else:
                chk_status, chk_result = "in_progress", None
            # legacy PASS/FAIL on oldest rows
            if chk_result and chk_created.year <= 2020 and r.random() < 0.3:
                chk_result = "PASS" if chk_result == "clear" else "FAIL"

            # reports inside this check: document + facial_similarity always; watchlist often
            rep_id_doc = "rep_" + det_uuid(("rep_doc", cust.cid, ci))
            rep_id_face = "rep_" + det_uuid(("rep_face", cust.cid, ci))
            has_watchlist = r.random() < 0.7
            rep_id_wl = "rep_" + det_uuid(("rep_wl", cust.cid, ci)) if has_watchlist else None
            report_ids = [rep_id_doc, rep_id_face] + ([rep_id_wl] if has_watchlist else [])

            completed_epoch = ts_epoch_s(chk_created + dt.timedelta(
                minutes=r.randint(2, 240))) if chk_status == "complete" else None

            checks.append((
                chk_id, applicant_id, chk_status, chk_result,
                json.dumps(r.sample(["onboarding", "reverify", "high_value", "edd"],
                                    k=r.randint(0, 2))),
                json.dumps(report_ids),
                maybe_null(f"https://app.nala.com/onfido/redirect/{chk_id}", 0.6, r),
                r.random() < 0.5,
                ts_isoz(chk_created),
                completed_epoch,
                f"https://api.onfido.com/v3/checks/{chk_id}",
                json.dumps([det_uuid(("wh", cust.cid, ci))]),
            ))

            # ---- document report + the underlying document ----
            doc_sub = r.choices(["clear", "rejected", "suspected", "caution"],
                                weights=[88, 4, 3, 5])[0]
            reports.append((
                rep_id_doc, chk_id, applicant_id, "document",
                "complete" if chk_status == "complete" else "awaiting_data",
                "clear" if doc_sub == "clear" else "consider",
                doc_sub,
                json.dumps({"data_comparison": {"result": doc_sub},
                            "data_validation": {"result": "clear"}}),
                json.dumps({"document_type": r.choice(DOC_TYPES)}),
                json.dumps(["doc_" + det_uuid(("doc", cust.cid, ci))]),
                ts_isoz(chk_created),
                ts_isoz(chk_created) if chk_status == "complete" else None,
                f"https://api.onfido.com/v3/reports/{rep_id_doc}",
            ))
            dtype = r.choice(DOC_TYPES)
            dnum = _doc_number(r)
            documents.append((
                "doc_" + det_uuid(("doc", cust.cid, ci)),
                applicant_id, dtype,
                r.choice(["front", "back", None]) if dtype != "passport" else None,
                ISO3.get(cust.country, "GBR"),
                dnum[-4:], _sha256(dnum),               # governed: last4 + hash
                cust.first, cust.last, cust.dob,
                maybe_null("2029-12-31", 0.2, r),
                f"{dtype}_{cust.cid}.jpg", "image/jpeg",
                r.randint(80_000, 4_000_000),
                f"https://api.onfido.com/v3/documents/doc_{cust.cid}/download",
                ts_isoz(chk_created),
            ))

            # ---- facial similarity report ----
            face_result = "clear" if r.random() < 0.92 else "consider"
            facial.append((
                rep_id_face, chk_id, applicant_id,
                r.choice(["standard", "video", "motion"]),
                face_result,
                "clear" if face_result == "clear" else r.choice(["suspected", "caution"]),
                maybe_null(round(r.uniform(0.62, 0.999), 4), 0.25, r),
                json.dumps({"face_match": {"result": face_result,
                                           "properties": {"score": round(r.uniform(0.6, 1.0), 3)}}}),
                json.dumps({"image_integrity": {"result": "clear"}}),
                json.dumps({"visual_authenticity": {"result": face_result}}),
                ts_isoz(chk_created),
                ts_isoz(chk_created) if chk_status == "complete" else None,
            ))

            # ---- watchlist report ----
            if has_watchlist:
                n_matches = 0 if r.random() < 0.93 else r.randint(1, 4)
                wl_result = "clear" if n_matches == 0 else "consider"
                recs = [{"name": cust.first + " " + cust.last,
                         "match_types": r.sample(["name_exact", "aka_exact", "name_fuzzy"], k=1),
                         "sources": r.sample(WATCHLIST_SOURCES, k=r.randint(1, 2))}
                        for _ in range(n_matches)]
                watchlist.append((
                    rep_id_wl, chk_id, applicant_id,
                    r.choice(["standard", "enhanced", "peps_only", "sanctions_only"]),
                    wl_result, n_matches,
                    json.dumps(recs),
                    json.dumps(r.sample(WATCHLIST_SOURCES, k=r.randint(2, 4))),
                    r.random() < 0.5,
                    ts_isoz(chk_created),
                    ts_isoz(chk_created) if chk_status == "complete" else None,
                ))

    bulk_copy(conn, f"{SCHEMA}.applicants",
              ["id", "external_id", "nala_customer_uuid", "first_name", "last_name",
               "email", "dob", "address_line1", "address_town", "address_postcode",
               "address_country", "phone_number", "id_numbers", "created_at", "href",
               "sandbox", "is_deleted", "deleted_at"], applicants)
    bulk_copy(conn, f"{SCHEMA}.checks",
              ["id", "applicant_id", "status", "result", "tags", "report_ids",
               "redirect_uri", "applicant_provides_data", "created_at",
               "completed_at_epoch", "href", "webhook_ids"], checks)
    bulk_copy(conn, f"{SCHEMA}.reports",
              ["id", "check_id", "applicant_id", "name", "status", "result",
               "sub_result", "breakdown", "properties", "documents", "created_at",
               "completed_at", "href"], reports)
    bulk_copy(conn, f"{SCHEMA}.documents",
              ["id", "applicant_id", "type", "side", "issuing_country",
               "document_number_last4", "document_number_hash", "first_name",
               "last_name", "dob", "expiry_date", "file_name", "file_type",
               "file_size", "download_href", "created_at"], documents)
    bulk_copy(conn, f"{SCHEMA}.facial_similarity_reports",
              ["id", "check_id", "applicant_id", "variant", "result", "sub_result",
               "score", "face_comparison", "image_integrity", "visual_authenticity",
               "created_at", "completed_at"], facial)
    bulk_copy(conn, f"{SCHEMA}.watchlist_reports",
              ["id", "check_id", "applicant_id", "variant", "result", "n_matches",
               "records", "sources_searched", "shared_with_third_parties",
               "created_at", "completed_at"], watchlist)

    print(f"[{SCHEMA}] applicants={len(applicants)} checks={len(checks)} "
          f"reports={len(reports)} documents={len(documents)} "
          f"facial={len(facial)} watchlist={len(watchlist)}")


if __name__ == "__main__":
    c = connect()
    main(c)
    c.close()
