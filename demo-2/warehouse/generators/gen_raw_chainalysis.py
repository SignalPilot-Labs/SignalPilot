"""
Generator: raw_chainalysis — crypto wallet risk screening.

NALA/Rafiki settle in stablecoins, so deposit/withdrawal wallet addresses get
screened. We screen addresses for a subset of customers (those who touched
crypto) plus a population of pure counterparty wallets. High/Severe screenings
spawn alerts; every screening gets a few exposure breakdown lines.
"""
from __future__ import annotations

import datetime as dt
import json

from common import (
    connect, ensure_schema, apply_ddl_file, truncate, bulk_copy,
    customer_master, rng, rand_datetime, maybe_null,
    ts_isoz, ts_epoch_ms, det_uuid, STABLECOINS, N,
)

SCHEMA = "raw_chainalysis"
DDL = "sql/ddl/raw_chainalysis.sql"

ASSET_NETWORK = {"USDC": ["ethereum", "polygon", "base"],
                 "USDT": ["ethereum", "tron"],
                 "PYUSD": ["ethereum"],
                 "ETH": ["ethereum"], "TRX": ["tron"]}
CATS_CLEAN = ["exchange", "p2p exchange", "merchant services", "defi",
              "mining", "hosted wallet"]
CATS_RISK = ["sanctioned entity", "darknet market", "scam", "stolen funds",
             "mixing", "terrorist financing", "fraud shop", "ransomware"]
RISK_LEVELS = ["Low", "Medium", "High", "Severe"]


def _eth_addr(r):
    return "0x" + "".join(r.choice("0123456789abcdef") for _ in range(40))


def _tron_addr(r):
    return "T" + "".join(r.choice("123456789ABCDEFGHJKLMNPQRSTUVWXYZabcdefghijkmnopqrstuvwxyz")
                         for _ in range(33))


def _addr(r, network):
    return _tron_addr(r) if network == "tron" else _eth_addr(r)


def main(conn):
    ensure_schema(conn, SCHEMA)
    apply_ddl_file(conn, DDL)
    truncate(conn, f"{SCHEMA}.address_screenings", f"{SCHEMA}.screening_alerts",
             f"{SCHEMA}.exposure")

    customers = customer_master()
    screenings, alerts, exposures = [], [], []
    exp_seq = 0

    def emit_screening(key, customer_code):
        nonlocal exp_seq
        r = rng("chain", key)
        asset = r.choice(STABLECOINS + ["ETH", "TRX"])
        network = r.choice(ASSET_NETWORK[asset])
        address = _addr(r, network)
        scr_id = "scr_" + det_uuid(("chain_scr", key))
        requested = rand_datetime(r, start=dt.date(2022, 1, 1))

        roll = r.random()
        if roll < 0.90:
            risk = r.choice(["Low", "Medium"])
        elif roll < 0.98:
            risk = "High"
        else:
            risk = "Severe"
        sanctioned = risk == "Severe" and r.random() < 0.6
        if sanctioned:
            cat = "sanctioned entity"
            cluster = r.choice(["Lazarus Group", "Garantex", "Hydra Market", "Tornado Cash"])
        elif risk in ("High", "Severe"):
            cat = r.choice(CATS_RISK)
            cluster = r.choice(["Unknown", "Suspicious Cluster", "Hydra Market"])
        else:
            cat = r.choice(CATS_CLEAN)
            cluster = r.choice(["Binance", "Coinbase", "Kraken", "Circle", "Unknown"])

        direction = r.choice(["DEPOSIT", "WITHDRAWAL"])
        screenings.append((
            scr_id, address, asset, network,
            customer_code,
            direction, risk,
            maybe_null(f"{cat} exposure detected", 0.4, r),
            cluster, cat, sanctioned,
            r.choices(["COMPLETE", "PENDING", "ERROR"], weights=[96, 3, 1])[0],
            ts_isoz(requested),
            ts_isoz(requested + dt.timedelta(seconds=r.randint(1, 90))),
            json.dumps({"address": address, "asset": asset, "risk": risk,
                        "cluster": {"name": cluster, "category": cat}}),
        ))

        # alert on High/Severe
        if risk in ("High", "Severe"):
            a_status = r.choices(["OPEN", "IN_REVIEW", "DISMISSED", "CONFIRMED"],
                                 weights=[20, 25, 40, 15])[0]
            alerts.append((
                "alrt_" + det_uuid(("chain_alrt", key)),
                scr_id, address,
                risk,
                cat if cat in CATS_RISK else r.choice(CATS_RISK),
                cluster,
                r.choice(["DIRECT", "INDIRECT"]),
                round(r.uniform(100, 250000), 2),
                round(r.uniform(50, 100000), 2),
                ts_epoch_ms(requested + dt.timedelta(minutes=r.randint(1, 60))),
                a_status,
                maybe_null(r.choice(["confirmed true positive", "false positive on review",
                                     "escalated to MLRO"]), 0.5, r),
                ts_isoz(requested),
            ))

        # exposure breakdown: a few lines per screening
        n_exp = r.randint(2, 5)
        cats_pool = CATS_CLEAN + ([cat] if cat in CATS_RISK else [])
        for _ in range(n_exp):
            exp_seq += 1
            exposures.append((
                exp_seq, scr_id, address,
                r.choice(["SENT", "RECEIVED"]),
                r.choice(cats_pool),
                r.choice(["DIRECT", "INDIRECT"]),
                round(r.uniform(0, 500000), 2),
                maybe_null(round(r.uniform(0, 1), 4), 0.3, r),
                maybe_null(cluster, 0.5, r),
                ts_isoz(requested),
            ))

    # ~12% of customers touched crypto and got at least one wallet screened.
    for cust in customers:
        rc = rng("chain_cust", cust.cid)
        if rc.random() < 0.12:
            n = 1 + (1 if rc.random() < 0.3 else 0)
            for k in range(n):
                emit_screening(("cust", cust.cid, k), cust.code)

    # pure counterparty wallets (no NALA customer code).
    n_counterparty = max(50, N["customers"] // 4)
    for i in range(n_counterparty):
        emit_screening(("cp", i), None)

    bulk_copy(conn, f"{SCHEMA}.address_screenings",
              ["id", "address", "asset", "network", "nala_customer_code", "direction",
               "risk", "risk_reason", "cluster_name", "cluster_category",
               "is_sanctioned", "status", "requested_at", "updated_at",
               "raw_response"], screenings)
    bulk_copy(conn, f"{SCHEMA}.screening_alerts",
              ["id", "screening_id", "address", "alert_level", "category", "service",
               "exposure_type", "exposure_usd", "alert_amount_usd",
               "triggered_at_epoch_ms", "status", "disposition", "created_at"], alerts)
    bulk_copy(conn, f"{SCHEMA}.exposure",
              ["id", "screening_id", "address", "direction", "category",
               "exposure_type", "value_usd", "percentage", "cluster_name",
               "created_at"], exposures)

    print(f"[{SCHEMA}] screenings={len(screenings)} alerts={len(alerts)} "
          f"exposures={len(exposures)}")


if __name__ == "__main__":
    c = connect()
    main(c)
    c.close()
