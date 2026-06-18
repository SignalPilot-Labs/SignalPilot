# NALA demo — recreate on a new machine

A self-contained demo: a deliberately messy, PII-bearing **NALA** (cross-border
remittance) Postgres warehouse, a ~100-model dbt project, an analyst dashboard,
and an "upstream break trips up an LLM" harness.

> Everything runs against ONE isolated Postgres (`nala_warehouse`, host port
> **5602**). It never touches any other database/stack.

## Prerequisites
- Docker
- Python 3.12+
- (optional) the Claude Code CLI for the `llm-trap/` experiments

## 1. Start the warehouse Postgres
```bash
cd demo-2/warehouse
docker compose -f docker-compose.nala.yml up -d        # add MSYS_NO_PATHCONV=1 on Git-Bash/Windows
# -> postgres on localhost:5602, db nala_warehouse, user/pass nala/nala_dev_only
```

## 2. Python env
```bash
cd demo-2
python -m venv warehouse/.venv
warehouse/.venv/Scripts/pip install -r requirements.txt     # Windows
# warehouse/.venv/bin/pip install -r requirements.txt       # macOS/Linux
```

## 3. Generate the warehouse data (raw_* schemas)
Scale is set by `NALA_SCALE` in `warehouse/.env` (`test` ≈ seconds, `demo` ≈
minutes / ~25GB, `large` ≈ tens of GB). Row counts live in
`warehouse/generators/common.py`.
```bash
cd demo-2/warehouse
NALA_SCALE=demo .venv/Scripts/python.exe generators/run_all.py
```
This loads ~157 tables across 29 `raw_*` source-system schemas. The generators
are idempotent. `common.py` is the shared contract (connection, deterministic
PII identities, bulk COPY, reference data) — every `gen_*.py` imports it.

## 4. Build the dbt models
The CORRECT build (clean marts in `analytics_*`):
```bash
cd demo-2/nala_dbt
../warehouse/.venv/Scripts/dbt.exe build --profiles-dir .
```
The BROKEN build (3 deliberately-broken intermediates, also into `analytics_*` —
overwrites the clean marts; used for the LLM trap):
```bash
cd demo-2/nala_dbt_test
../warehouse/.venv/Scripts/dbt.exe run --profiles-dir .
```
Both projects target the `analytics` schema, so whichever you run last wins —
that's the broken<->correct toggle. See `nala_dbt_test/README.md`.

## 5. Dashboard
```bash
cd demo-2/dashboard
../warehouse/.venv/Scripts/python.exe -m jupyter nbconvert --to notebook \
  --execute --inplace nala_dashboard.ipynb
```

## 6. LLM trap (optional)
Dockerized Claude Code CLI given a Slack-style question against the broken
pipeline. Needs `CLAUDE_KEY_1` (an OAuth token) in a repo-root `.env`. See
`llm-trap/README.md` and `nala_dbt_test/PROMPTS.md` (prompts + answer key).

## What's where
| path | what |
|------|------|
| `company-profile.md` | the NALA business this is modeled on |
| `warehouse/` | docker compose, `.env`, DDL (`sql/ddl/`), generators, SPEC |
| `business-definitions/` | one doc per table (157) + `OVERVIEW.md` |
| `nala_dbt/` | the dbt project (clean) |
| `nala_dbt_test/` | the dbt project with the 3 breaks + `PROMPTS.md` |
| `dashboard/` | analyst notebook + "break it" guide |
| `llm-trap/` | dockerized CC CLI trap harness |

## Connection URL
- from your host: `postgresql://nala:nala_dev_only@localhost:5602/nala_warehouse`
- from a container on the warehouse network: `...@nala-warehouse-pg:5432/...`
- from another container: `...@host.docker.internal:5602/...`
