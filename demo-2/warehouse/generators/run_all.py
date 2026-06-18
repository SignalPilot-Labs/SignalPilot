"""
Orchestrator: apply every schema's DDL and run every generator.

Usage:
  NALA_SCALE=test ./.venv/Scripts/python.exe generators/run_all.py
  NALA_SCALE=demo ./.venv/Scripts/python.exe generators/run_all.py
  # subset:
  NALA_SCALE=test ./.venv/Scripts/python.exe generators/run_all.py raw_stripe raw_fx
"""
import importlib
import sys
import time
import traceback

from common import connect, SCALE, N

# core_transfers is the anchor (everything references its customers/transfers),
# so load it first; order is otherwise irrelevant (no cross-schema FKs).
SCHEMAS = [
    "raw_core_transfers",
    "raw_rafiki",
    "raw_ledger", "raw_fireblocks", "raw_circle",
    "raw_fx", "raw_openexchange",
    "raw_mpesa", "raw_flutterwave",
    "raw_stripe", "raw_plaid", "raw_marqeta",
    "raw_onfido", "raw_complyadvantage", "raw_chainalysis", "raw_compliance",
    "raw_segment", "raw_amplitude", "raw_appsflyer", "raw_app_store",
    "raw_braze", "raw_google_ads", "raw_meta_ads", "raw_zendesk", "raw_intercom",
    "raw_twilio", "raw_sendgrid", "raw_netsuite", "raw_workday",
]


def main():
    targets = sys.argv[1:] or SCHEMAS
    print(f"scale={SCALE}  customers={N['customers']}  transfers={N['transfers']}")
    ok, failed = [], []
    for schema in targets:
        mod_name = f"gen_{schema}"
        t0 = time.time()
        try:
            mod = importlib.import_module(mod_name)
            conn = connect()
            mod.main(conn)
            conn.close()
            dt = time.time() - t0
            print(f"  OK   {schema:24s} {dt:6.1f}s")
            ok.append(schema)
        except Exception:
            print(f"  FAIL {schema}")
            traceback.print_exc()
            failed.append(schema)
    print(f"\n{len(ok)} ok, {len(failed)} failed")
    if failed:
        print("FAILED:", ", ".join(failed))
        sys.exit(1)


if __name__ == "__main__":
    main()
