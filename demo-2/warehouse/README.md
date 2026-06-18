# NALA Demo Warehouse

A deliberately **messy, enterprise-grade** Postgres warehouse that mimics the real
data estate of **NALA** (cross-border remittance fintech — consumer app + Rafiki
B2B API). Built for creating realistic demo use cases: dirty data, PII, ~157 tables
across 29 source systems, and a ~100-model dbt project on top.

> See `../company-profile.md` for the business, `SPEC.md` for build conventions,
> and `../business-definitions/OVERVIEW.md` for the per-table data dictionary.

## Isolation / safety

This stack is **fully isolated** from the main SignalPilot stack:
- Container `nala-warehouse-pg`, volume `nala_wh_pgdata`, network `nala-warehouse_default`
- Host port **5602** (main stack uses 5601/3300/3200/2718 — no overlap)
- Nothing here touches the existing `docker-compose.yml`.

## Start / stop

```bash
cd demo-2/warehouse
MSYS_NO_PATHCONV=1 docker compose -f docker-compose.nala.yml up -d   # start
docker compose -f docker-compose.nala.yml down                       # stop (keeps data)
docker compose -f docker-compose.nala.yml down -v                    # stop + wipe data
```

Connection: `postgresql://nala:nala_dev_only@localhost:5602/nala_warehouse`

## Generate data

Python venv (already created at `.venv`) has `faker` + `psycopg2`. Scale is set by
`NALA_SCALE` in `.env` (`test` ≈ seconds, `demo` ≈ a few-to-tens of GB, `large` ≈
tens of GB+). Row counts live in `generators/common.py`.

```bash
# everything
NALA_SCALE=demo ./.venv/Scripts/python.exe generators/run_all.py
# a subset
NALA_SCALE=test ./.venv/Scripts/python.exe generators/run_all.py raw_stripe raw_fx
# one source
NALA_SCALE=test ./.venv/Scripts/python.exe generators/gen_raw_mpesa.py
```

Generators are **idempotent**: each ensures its schema, applies its DDL, truncates,
and reloads. Re-running fully rebuilds that slice.

### The shared contract — `generators/common.py`

Single source of truth every generator imports. Provides the connection, scale-aware
row counts (`N`), reference data (currencies / receive markets / partners), the
**bulk COPY loader**, and **deterministic identity helpers** — the same canonical
`customer_id` yields the same email / phone / name / DOB across *every* source system
(with realistic dirtiness via `dirty_email` / `dirty_phone`). That determinism is what
makes cross-source identity-resolution demos possible.

## dbt project

Lives in `../nala_dbt`. ~100 models: ~61 staging (views, 1:1 with raw, clean up the
mess), ~21 intermediate (views), ~19 marts (**materialized as tables** — this mimics
the real dbt build/materialization workflow, so the DB ends up with both raw source
tables *and* dbt-built analytics tables).

```bash
cd ../nala_dbt
../warehouse/.venv/Scripts/dbt.exe build --profiles-dir .     # run + test everything
../warehouse/.venv/Scripts/dbt.exe run   --profiles-dir . --select staging
../warehouse/.venv/Scripts/dbt.exe run   --profiles-dir . --select marts
```

Output schemas: `analytics_staging` (views), `analytics_intermediate` (views),
`analytics_marts` (tables).

## What's "messy" on purpose

- Timestamp format drift across systems: ISO, ISO-Z, epoch seconds, epoch ms, naive vs tz.
- Money-unit drift: minor units (cents/micros) vs major, strings vs numerics.
- Vendor-authentic naming (M-PESA `TransactionID`/`MSISDN` CamelCase, Stripe `ch_`/
  `created` epoch-s, etc.) — snake_case normalization happens in staging.
- Legacy/duplicate tables (`saved_recipients`), legacy enum values (`PENDING_OLD`),
  soft-delete flags, sparse nullable columns, jsonb vendor payload blobs, a deliberate
  SCD `is_current` bug in risk scores (staging derives a trustworthy `is_latest`).
- Cross-system join keys are intentionally dirty (uppercased / spaced / null) so
  identity resolution is realistic.

## PII

Treated as a governed financial dataset (all fake data). PII columns are tagged in
every table's business-definition doc. Governance patterns are modeled: card `last4` +
`bin` (never full PAN), `national_id` alongside `national_id_hash`, API key prefix + hash.
See `../business-definitions/OVERVIEW.md` (223 PII-tagged columns).

## Layout

```
warehouse/
  docker-compose.nala.yml   # isolated PG on 5602
  .env                      # connection + NALA_SCALE
  SPEC.md                   # build contract (read this)
  sql/ddl/<schema>.sql      # one DDL file per source schema (29)
  generators/
    common.py               # shared contract
    gen_<schema>.py         # one generator per source schema (29)
    run_all.py              # orchestrator
../nala_dbt/                # dbt project (~100 models)
../business-definitions/    # one doc per table (157) + OVERVIEW.md
```
