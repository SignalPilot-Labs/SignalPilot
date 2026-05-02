# Spider2-Lite Cloud Connection Setup — Fixes & Verification Log

What the local SQLite optimization run (rounds 1–7, 80% held-out) didn't cover: the **412 cloud tasks** (180 BigQuery + 207 Snowflake + 25 GA4-on-BigQuery). This file captures every change made to wire up cloud DB execution end-to-end. It is the brain dump for a fresh session that needs to pick up the cloud loop without re-discovering plumbing.

---

## 1. Quick status

| Backend | Auth | Verified | Notes |
|---|---|---|---|
| BigQuery | Service-account JSON, billed against SA's home project | ✅ `SELECT 1` and `SELECT COUNT(*) FROM` bigquery-public-data.google_analytics_sample.ga_sessions_20170801` returned **2556 rows** | Spider2 BQ data lives in `bigquery-public-data.*` (and similar public projects); SQL must fully qualify. SA's project is the **billing project**, not the data project. |
| Snowflake | PAT (JWT) used as password against shared Spider2 account `RSRSBDK-YDB67606` | ✅ `SELECT 1`, `INFORMATION_SCHEMA.DATABASES` returned **157 dbs** | Schema names in some DBs differ from local resource folder (see §4). Token expires **2026-07-12** — refresh after that. |
| Gateway | localhost:3300, container `signalpilot-gateway-1` | ✅ Running, MCP path bypasses auth via local context vars | If the gateway dies, restart with `docker compose -f docker-compose.yml up -d gateway`. |

---

## 2. Files modified / created

### 2.1 `.env` — Snowflake credentials

Required keys (the runner reads these via `_load_dotenv_file` in `benchmark/core/mcp.py`):

```
SNOWFLAKE_ACCOUNT=RSRSBDK-YDB67606
SNOWFLAKE_USER=<participant_username>
SNOWFLAKE_TOKEN="<JWT_PAT>"
# Optional (defaults shown):
# SNOWFLAKE_WAREHOUSE=COMPUTE_WH_PARTICIPANT
# SNOWFLAKE_ROLE=PARTICIPANT
```

**Pitfall observed**: keys were initially named `SPIDER2-SNOWFLAKES-ACCOUNT/USERNAME/TOKEN` — those are *not* what the code reads. The code checks for exactly `SNOWFLAKE_ACCOUNT`, `SNOWFLAKE_USER`, `SNOWFLAKE_TOKEN`. Renaming silently fixes "auth failed" or empty-connection errors.

### 2.2 `gcp-service-account.json` — BigQuery SA

Path is hardcoded in `benchmark/core/paths.py`:
```python
BIGQUERY_SA_FILE = PROJECT_ROOT / "gcp-service-account.json"
```

Required roles on the SA (granted at the SA's home project):
- `roles/bigquery.jobUser` — needed to run query jobs (this is what was missing the first attempt; got 403 "User does not have bigquery.jobs.create permission in project spider2-public-data" until we switched billing project — see §2.3).
- `roles/bigquery.dataViewer` — for any datasets you create in your own project.
- `roles/bigquery.readSessionUser` — for the Storage API (faster reads).

The SA's home project must have **billing enabled**. Public datasets like `bigquery-public-data` are world-readable, but BQ jobs are always billed to the *caller's* project.

**Gitignore covers both `.env` and `gcp-service-account.json`** — verified.

### 2.3 `benchmark/runners/sql_runner.py` — BQ billing project fix

Original code (broken):
```python
if backend == DBBackend.BIGQUERY:
    project: str = task.get("project_id", task.get("project", ""))
    dataset: str = task.get("dataset", task.get("schema", ""))
    if not project:
        project = "spider2-public-data"   # ← used SA cannot create jobs here
        log(...)
    if not dataset:
        dataset = task.get("db", "")      # ← would auto-prefix `spider2-public-data.<db>`
    return register_bigquery_connection(instance_id, project, dataset)
```

Fixed code: read the SA JSON's `project_id` and pass it as the **billing project**; pass empty `dataset` so the BQ driver does **not** set `default_dataset = f"{project}.{dataset}"` (which would produce a nonexistent path).

```python
if backend == DBBackend.BIGQUERY:
    billing_project: str = ""
    try:
        import json as _json
        from ..core.paths import BIGQUERY_SA_FILE
        if BIGQUERY_SA_FILE.exists():
            billing_project = _json.loads(BIGQUERY_SA_FILE.read_text()).get("project_id", "")
    except Exception as e:
        log(f"Could not read SA project_id: {e}", "WARN")
    if not billing_project:
        log(f"Task '{instance_id}': no SA project_id available; BQ jobs will fail", "WARN")
    return register_bigquery_connection(instance_id, billing_project, "")
```

**Why this works**: Spider2-Lite gold SQL fully qualifies tables like `` `bigquery-public-data.google_analytics_sample.ga_sessions_*` `` (verified against `evaluation_suite/gold/sql/bq001.sql`). The agent doesn't need a default dataset — it just needs a project to bill jobs against. The SA's home project (`gen-lang-client-0116348390` in our case) has `bigquery.jobs.create`, so jobs run there and read public data through fully-qualified refs.

---

## 3. Verification recipes (paste-ready)

### 3.1 Read the local API key (gateway-side, for direct `/api/query` testing)
```bash
KEY=$(docker exec signalpilot-gateway-1 cat /shared/local_api_key)
echo "$KEY"
```

### 3.2 BigQuery smoke
```bash
KEY=$(docker exec signalpilot-gateway-1 cat /shared/local_api_key)
python3 - <<'PY'
import json, urllib.request
sa = open('/Users/tarik/codeAlpine/SignalPilot/gcp-service-account.json').read()
billing = json.loads(sa)["project_id"]
payload = json.dumps({"name":"bq_smoke","db_type":"bigquery","project":billing,
                      "dataset":"","credentials_json":sa,"description":"smoke"}).encode()
try: urllib.request.urlopen(urllib.request.Request("http://localhost:3300/api/connections/bq_smoke", method="DELETE"), timeout=5)
except: pass
urllib.request.urlopen(urllib.request.Request("http://localhost:3300/api/connections", data=payload, headers={"Content-Type":"application/json"}, method="POST"), timeout=15)
PY
curl -s -X POST -H "Authorization: Bearer $KEY" -H 'Content-Type: application/json' \
  http://localhost:3300/api/query \
  -d '{"connection_name":"bq_smoke","sql":"SELECT COUNT(*) AS n FROM `bigquery-public-data.google_analytics_sample.ga_sessions_20170801`"}'
# expected: {"rows":[{"n":2556}], ...}
curl -s -X DELETE -H "Authorization: Bearer $KEY" http://localhost:3300/api/connections/bq_smoke
```

### 3.3 Snowflake smoke
```bash
KEY=$(docker exec signalpilot-gateway-1 cat /shared/local_api_key)
python3 - <<'PY'
import json, urllib.request
env = {l.split("=",1)[0].strip(): l.split("=",1)[1].strip().strip('"')
       for l in open('/Users/tarik/codeAlpine/SignalPilot/.env') if "=" in l and not l.startswith("#")}
payload = {"name":"sf_smoke","db_type":"snowflake","account":env["SNOWFLAKE_ACCOUNT"],
           "username":env["SNOWFLAKE_USER"],"password":env["SNOWFLAKE_TOKEN"],
           "database":"SNOWFLAKE","warehouse":env.get("SNOWFLAKE_WAREHOUSE","COMPUTE_WH_PARTICIPANT"),
           "role":env.get("SNOWFLAKE_ROLE","PARTICIPANT"),"schema_name":"INFORMATION_SCHEMA","description":"smoke"}
try: urllib.request.urlopen(urllib.request.Request("http://localhost:3300/api/connections/sf_smoke", method="DELETE"), timeout=5)
except: pass
urllib.request.urlopen(urllib.request.Request("http://localhost:3300/api/connections", data=json.dumps(payload).encode(), headers={"Content-Type":"application/json"}, method="POST"), timeout=15)
PY
curl -s -X POST -H "Authorization: Bearer $KEY" -H 'Content-Type: application/json' \
  http://localhost:3300/api/query \
  -d '{"connection_name":"sf_smoke","sql":"SELECT CURRENT_USER() AS u, CURRENT_ROLE() AS r"}'
curl -s -X POST -H "Authorization: Bearer $KEY" -H 'Content-Type: application/json' \
  http://localhost:3300/api/query \
  -d '{"connection_name":"sf_smoke","sql":"SELECT COUNT(*) AS n FROM SNOWFLAKE.INFORMATION_SCHEMA.DATABASES"}'
# expected: 157 rows visible to the participant role
curl -s -X DELETE -H "Authorization: Bearer $KEY" http://localhost:3300/api/connections/sf_smoke
```

### 3.4 PAT expiry check
```bash
python3 - <<'PY'
import json, base64, datetime, os
tok = next(l.split("=",1)[1].strip().strip('"') for l in open(os.path.expanduser('/Users/tarik/codeAlpine/SignalPilot/.env'))
           if l.startswith("SNOWFLAKE_TOKEN"))
payload = json.loads(base64.urlsafe_b64decode(tok.split('.')[1] + "==").decode())
print("exp:", datetime.datetime.fromtimestamp(payload['exp'], tz=datetime.UTC).isoformat())
print("now:", datetime.datetime.now(tz=datetime.UTC).isoformat())
PY
```

---

## 4. Snowflake schema-mapping caveat

The local `resource/databases/snowflake/<DB>/<SCHEMA>/` folders sometimes name a schema that **the participant role cannot see**. Concrete example: `GLOBAL_WEATHER__CLIMATE_DATA_FOR_BI` has local resources under `STANDARD_TILE/`, but the participant role only sees `PWS_BI_SAMPLE/` in that DB, with similarly-named-but-not-identical tables.

| DB | Local resource schema | Participant-visible schema |
|---|---|---|
| `GLOBAL_WEATHER__CLIMATE_DATA_FOR_BI` | `STANDARD_TILE` | `PWS_BI_SAMPLE` |

This means the gold SQL in `evaluation_suite/gold/sql/sf001.sql` references `GLOBAL_WEATHER__CLIMATE_DATA_FOR_BI.standard_tile.history_day` which the SA cannot query — the gold itself fails for at least some sf tasks under this account. **Implication**: not all 207 SF tasks will be runnable end-to-end with this PAT. We should expect:
- Some sf tasks will fail at execution time with `Schema 'X' does not exist or not authorized`.
- Add a Layer-1 check that classifies these as **environment failures**, not model failures, and excludes them from the optimization signal.
- Alternatively, the agent's first move on a SF task should be to query `INFORMATION_SCHEMA.SCHEMATA` to discover what's actually accessible, and to remap if the resource directory and live DB diverge.

This is captured as an open question for round 1 of the cloud loop.

---

## 5. Things that already work without any changes

- `_get_skill_names()` in `sql_runner.py` already routes to the right dialect skill: `bigquery-sql` for BQ, `snowflake-sql` for SF, `sqlite-sql` for local. Plus the pattern skills (output-column-spec, temporal-comparison, etc.) load for every backend.
- `_determine_backend()` in `sql_runner.py` infers backend from `resource/databases/<bigquery|snowflake|sqlite>/<db>/` — no per-task wiring needed.
- The MCP server (`mcp_config.json`) bypasses gateway auth by setting `mcp_user_id_var.set('local')` before launching, so the agent's MCP tools work without an API key.
- `register_snowflake_connection` and `register_bigquery_connection` in `core/mcp.py` already POST the right payload shape to the gateway HTTP API.
- `clear_all_connections()` cleans up stale registrations between runs.

---

## 6. Outstanding / follow-ups

1. **Smoke an end-to-end pipeline run** on `bq001` and `sf001` once the connection-setup branch is checked out fresh. (Aborted mid-run during this session because a fresh session was started.)
2. **Sampler scope for cloud**: `held_out_set(suite, n=20, task_filter="local")` currently only filters by single prefix. Cloud needs either:
   - A `task_filters: list[str]` extension (e.g., `["sf","bq","ga"]`).
   - Or a new `cloud_held_out_set()` helper that draws stratified holdouts across the three kinds.
3. **Cost discipline**: BQ jobs scan public data billed against our SA's project. Snowflake jobs use shared compute against `COMPUTE_WH_PARTICIPANT`. Add a per-round `--max-bytes-billed` (BQ) and per-task wall-clock cap to bound spend.
4. **Result CSV vs `LIMIT 10000` injection**: the gateway's `inject_limit` adds `LIMIT 10000` to all queries. For tasks with > 10k expected rows, the result will be truncated and evaluation will fail spuriously. Need to either raise this cap for the benchmark gateway path or detect & re-issue without the cap. (This applies to local too but didn't bite there.)

---

## 7. Files changed (single commit ready)

```
modified:   benchmark/runners/sql_runner.py    # BQ billing project fix
modified:   .env                                # Snowflake creds (gitignored, do NOT commit)
new file:   gcp-service-account.json           # BQ SA (gitignored, do NOT commit)
new file:   cloud-connection-setup.md          # this doc
new file:   benchmark/AUTOFYN_CLOUD_PROMPT.md  # cloud loop brief
```

Suggested branch + commit:
```bash
git checkout -b chore/cloud-connection-setup
git add benchmark/runners/sql_runner.py cloud-connection-setup.md benchmark/AUTOFYN_CLOUD_PROMPT.md
git commit -m "cloud: BQ billing-project fix; setup log + cloud loop brief"
```
