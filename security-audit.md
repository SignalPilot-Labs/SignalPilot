# Security Audit — branch `autofyn/run-a-security-r-203054`

Scope: 51 changed files, ~8.7K LoC added vs `main`. Focus on the new
dbt-proxy (`gateway/dbt_proxy/`), the Knowledge Base API + MCP +
store, the dbt SQL validator, the model_blueprint / model_verify MCP
tools, the new knowledge UI, and `docker-compose.yml`.

Many V1–V6 + auth/error sanitization issues from prior rounds are
already mitigated and verified by `tests/test_security_fixes.py` —
those are NOT re-flagged here.

Findings are ordered **lowest → highest severity** as requested.
For each issue we note whether it is a true bug (must fix in **both**
modes) or **cloud-only hardening** (gate behind the existing `gateway.runtime.mode.is_cloud_mode()` helper (driven by `SP_DEPLOYMENT_MODE=cloud`); localhost dev must keep working).

Project rule applied throughout: localhost `docker compose up` must
keep working with no auth / no extra config; anything stricter is
cloud-only and env-gated.

---

## Info

### I-1 — Default Postgres password in `docker-compose.yml`
- File: `docker-compose.yml:15` (`POSTGRES_PASSWORD: ${POSTGRES_PASSWORD:-changeme_dev_only}`)
- The default password is `changeme_dev_only`. The variable name signals "dev only" — fine for localhost.
- **Mode:** Localhost only. Cloud deployments must NOT inherit this default; cloud compose / k8s manifests should require the var to be set.
- **Fix:** Keep default for local. In a cloud-mode compose/helm template, fail-fast if `POSTGRES_PASSWORD` is unset. No change required to this file for localhost.

### I-2 — Postgres port 5601 published on all host interfaces
- File: `docker-compose.yml:17-18`
- `ports: - "5601:5432"` binds 0.0.0.0:5601, exposing the DB to anything that can reach the dev machine on the LAN. With the default credential this is a real risk on shared networks.
- **Mode:** Cloud-only hardening. Localhost workflows still need DB access from host tooling.
- **Fix:** Bind to loopback explicitly: `"127.0.0.1:5601:5432"`. This still satisfies all dev tooling on the same host while removing LAN exposure. Apply unconditionally — it does not break `docker compose up`.

### I-3 — Sandbox container mounts arbitrary host path via `HOST_DATA_DIR`
- File: `docker-compose.yml:87` (`${HOST_DATA_DIR:-~}:/host-data:ro`)
- Default mounts the whole user home (`~`) read-only into the sandbox. Combined with the sandbox executing user code, this lets sandboxed dbt code read the user's home directory.
- **Mode:** Localhost feature. Cloud-only hardening.
- **Fix:** Document the `HOST_DATA_DIR` default and recommend users set a narrower directory; in cloud mode, require an explicit value (no `~` default). Annotate in the compose comment header.

### I-4 — Sandbox container runs with `SYS_ADMIN` + `SYS_PTRACE`
- File: `docker-compose.yml:70-75`
- `SYS_ADMIN` is required by gVisor; combined with `no-new-privileges`, `read_only: true`, `tmpfs /tmp`, mem/cpu/pids limits. This is the documented gVisor pattern.
- **Mode:** Both — but already constrained.
- **Fix:** No change. Document the dependency.

### I-5 — `current_setting()` deny-list may break legitimate dbt-postgres
- File: `gateway/engine/dbt_validation.py:163`
- `current_setting` is a built-in dbt-postgres often calls (`current_setting('search_path')`, etc.). Blocking it will break ordinary dbt runs.
- **Severity:** Functional, not exploitable, but listed because it lives in security code.
- **Fix:** Replace with a parameter-aware check (block only `current_setting('ssl_*' / 'config_file' / 'data_directory')` or treat unknown args as denied via a small allowlist). Both modes.

### I-6 — Long max TTL on run-tokens (24h) over cleartext pg-wire
- File: `gateway/dbt_proxy/api.py:42` (`ttl_seconds: int = Field(..., ge=60, le=86400)`)
- Tokens act as bearer credentials over a cleartext pg-wire handshake (R8 will add TLS). 24h is generous; passive capture on loopback is unlikely but possible inside a multi-tenant host.
- **Mode:** Cloud-only hardening.
- **Fix:** In cloud mode (`is_cloud_mode()` true, i.e. `SP_DEPLOYMENT_MODE=cloud`) cap TTL to e.g. 3600s. Localhost may keep 86400.

### I-7 — Audit-bypass DoS via fail-closed audit
- File: `gateway/dbt_proxy/audit.py:33-73`, `gateway/dbt_proxy/forwarder.py:60-68`
- Correct behaviour (must be fail-closed). However, every dbt statement issues a synchronous DB INSERT, so a flaky audit DB stalls the whole run. Already documented in the file header. Informational.
- **Fix:** None now; track for R8 batched audits.

---

## Low

### L-1 — `org_id` leaked into mint log line
- File: `gateway/dbt_proxy/api.py:127`
  `logger.info("dbt_proxy mint run_id=%s org=%s connector=%s", body.run_id, org_id, body.connector_name)`
- `tests/test_security_fixes.py::TestAuthErrorSanitization::test_auth_ok_does_not_log_org_id` already enforces that **auth_ok** does not log `org_id`. The masking policy in `RunTokenClaims.__repr__` masks `org_id`. The mint route violates the same policy.
- **Mode:** Both — fix unconditionally.
- **Fix:** Drop `org=%s` (or hash to a short fingerprint). `connector_name` should also be masked or kept high-cardinality safe.

### L-2 — Knowledge `scope_ref` accepts arbitrary characters up to 200
- File: `gateway/models/knowledge.py:88-95`
- Only length is validated. `scope_ref` is stored and rendered (after React text-safe rendering) and used as part of unique keys. Not a code-injection sink today (rendering is safe text), but inconsistent with other slug-validated fields.
- **Mode:** Both.
- **Fix:** Restrict to a slug-like regex (e.g. `^[A-Za-z0-9_./:-]{1,200}$`) and reject control characters.

### L-3 — `doc_id` (path param) not regex-validated
- File: `gateway/api/knowledge.py:81-149`
- Pydantic accepts any string for `doc_id` path params. Store queries are parameterised so SQLi is not possible, but a 36-char UUID format check would be cheaper than a DB roundtrip and prevents log noise / oversize keys.
- **Mode:** Both. Cheap fix.
- **Fix:** Validate as `uuid.UUID` in the path declaration: `doc_id: uuid.UUID`.

### L-4 — `_substitute_params` replaces `$N` everywhere (acknowledged limitation)
- File: `gateway/dbt_proxy/session.py:93-107`
- Uses `str.replace("$N", literal)`, which substitutes inside string literals and comments too. Documented in the file as a known R3 limitation; dbt-postgres does not produce queries that exhibit the corner case.
- **Mode:** Both. Track for R4.
- **Fix:** Track for R4 (parameterised execution). No code change needed now beyond keeping the safety check (NUL/NaN/Inf rejection).

### L-5 — Increment view counter swallows errors silently
- File: `gateway/store/knowledge.py:590-603`
- `increment_knowledge_view` swallows `Exception`. That is intended (best-effort), but the bare-`pass` masks malformed `doc_id` or org-mismatch attempts and hampers diagnostics.
- **Mode:** Both.
- **Fix:** `logger.debug` (not error) on failure so behaviour is unchanged but observable.

### L-6 — Markdown rendering preserves raw URL text but allows `data:` schemes if regex changes
- File: `signalpilot/web/app/knowledge/page.tsx:1234, 1343` (`SAFE_URL = /^https?:\/\//`)
- Currently safe (only http/https) and content is rendered through React (no `dangerouslySetInnerHTML`). Worth a comment so a future relaxation does not introduce `javascript:`/`data:` XSS.
- **Mode:** Both.
- **Fix:** Add a code comment "DO NOT broaden SAFE_URL — anchor allowlist required for XSS safety" near the regex.

### L-7 — Knowledge body size cap is 50 MiB regardless of plan
- File: `gateway/governance/knowledge_limits.py:5`
- A single doc may be 50 MiB even on the free plan; only the org quota constrains accumulation. An admin token with a small per-org quota of e.g. 50 MiB can still blow the budget in one POST.
- **Mode:** Cloud-only hardening.
- **Fix:** Tier-tied caps in cloud mode (e.g. free=256 KiB/doc, pro=2 MiB, etc.); local stays 50 MiB.

### L-8 — `gateway/db/engine.py` strips `?sslmode=...` from `DATABASE_URL`
- File: `gateway/db/engine.py:38-41`
- The query-string is stripped because asyncpg cannot parse it; SSL is then re-enabled if the original URL contained `sslmode=`. Subtle: any URL using `ssl=true` / `channel_binding=require` (without `sslmode=`) loses SSL.
- **Mode:** Cloud-relevant.
- **Fix:** Detect `ssl=`, `channel_binding=` patterns too, or fail-fast in cloud if SSL was requested but cannot be re-enabled.

### L-9 — All knowledge MCP proposals auto-accept (`_REVIEW_REQUIRED_CATEGORIES = {}`)
- File: `gateway/store/knowledge.py:54-55`, `gateway/mcp/tools/knowledge.py:198-260`
- `propose_knowledge` MCP tool inserts with `user_id=None, agent="propose_knowledge"`; every category falls into `_AUTO_ACCEPT_CATEGORIES`, so an agent can write directly to active docs without admin review.
- This matches the spec ("Knowledge requires human review by design" per the comment in `api/knowledge.py`, but the MCP path bypasses it because all categories are auto-accept).
- **Mode:** Cloud-only hardening (in localhost the agent IS the user). In cloud, agent-proposed docs should land in `pending` for at least some categories.
- **Fix:** When `agent is not None` AND `is_cloud_mode()` is true, force `status=pending` regardless of category. Localhost behaviour unchanged.

---

## Medium

### M-1 — SQL string-interpolation of DB-derived identifiers in `model_blueprint.py`
- File: `gateway/mcp/tools/model_blueprint.py:289-294, 504-559`
- Several queries are built by f-string interpolation of values returned from the warehouse itself: `WHERE table_name = '{tbl}'`, `'SELECT DISTINCT "{src_col_match}" ...'`, with `safe_val = str(r["status_val"]).replace("'", "''")` for some but not all interpolations (e.g. line 291 has no escaping).
- This is a **second-order SQL injection** sink: a malicious schema author (i.e. someone with table-create rights in the connected warehouse) could embed quotes / SQL in a table or column name that survives back to the gateway and is re-issued.
- **Mode:** Both — bug.
- **Fix:** Apply identifier quoting to ALL identifier interpolations: route through `_quote_table` and `'"' + col.replace('"','""') + '"'` for column names; for literal values use a parameterised driver call (most connectors here support parameter binding) or perform the exact `replace("'", "''")` then `f"'{...}'"` consistently.

### M-2 — `model_verify.py` interpolates table/column names from `information_schema`
- File: `gateway/mcp/tools/model_verify.py:798, 843, 845, 921-923, 937-939`
- Same class of issue as M-1. Lines 798/843 build `WHERE table_name = '{model_name}'` and `WHERE table_name = '{tbl}'`. `model_name` is regex-validated so it is safe; `tbl` comes from `SHOW TABLES` (DB-controlled). Same fix as M-1: escape single quotes for `tbl` before use, or use parameter binding.
- **Mode:** Both.

### M-3 — `_MODEL_NAME_RE` allows multi-segment names without segment limit
- File: `gateway/mcp/validation.py:9` (`r"^[a-zA-Z0-9_.]{1,256}$"`)
- `..` is allowed (e.g. `a..b`); resulting `_quote_table` produces `"a".""."b"` — empty-string identifier — likely a runtime error rather than an injection, but the regex should reject empty segments and leading/trailing dots.
- **Mode:** Both.
- **Fix:** Tighten to `^[a-zA-Z0-9_]+(\.[a-zA-Z0-9_]+){0,2}$` (max two dots = `database.schema.table`).

### M-4 — `dbt_validation` prefix bypass via leading-whitespace tricks (defence-in-depth only)
- File: `gateway/engine/dbt_validation.py:212-213`
- Prefix check uses `sql_lower.startswith(prefix)` and `f" {prefix}"` / `f"\n{prefix}"` membership. A statement like `;\tCOPY foo FROM PROGRAM ...` (tab between the semicolon and `COPY`) is not matched by the prefix check. The AST walk WOULD catch a `Command` node, so this is defence-in-depth, not a true bypass — but the prefix check should match any whitespace.
- **Mode:** Both.
- **Fix:** Match `\s+{prefix}` via regex instead of three explicit cases.

### M-5 — `propose_knowledge` MCP is unauthenticated in stdio mode
- File: `gateway/mcp/server.py:58-64`, `gateway/mcp/tools/knowledge.py:198-260`
- In stdio mode the org/user are pulled from `SP_ORG_ID`/static `"local"`. Anyone able to invoke the stdio MCP can write into any org by setting the env var. Acceptable for localhost (which is the whole point of stdio mode), but the audit should call this out.
- **Mode:** Cloud-only concern. In cloud, stdio mode must not be exposed.
- **Fix:** Document in `mcp/server.py` that stdio mode is for localhost only; `is_cloud_mode()` should refuse to launch stdio transport.

### M-6 — Audit row body persists full SQL plaintext (PII / credential risk)
- File: `gateway/dbt_proxy/audit.py:48-62`, `gateway/store/audit_log.py` (existing)
- Statement text including any literal values (which may include user secrets if a customer puts `password='...'` in a model) is stored in plaintext in `gateway_audit_logs.sql_text`. This is the existing audit-log policy, but new `dbt_proxy` traffic increases the volume and types of data captured.
- **Mode:** Cloud-only hardening (audit-at-rest already covered by DB encryption in cloud).
- **Fix:** Document. In cloud mode, ensure audit logs are written to an encrypted column or have row-level KMS. No code change required for localhost.

### M-7 — `connector_name` accepts any UTF-8 (no charset validation)
- File: `gateway/dbt_proxy/api.py:41` (`Field(..., min_length=1, max_length=64)`)
- Used as a key into the connector store and emitted via `peer ↔ run_id` logs. No injection sink today (parameterised store lookup), but worth tightening for parity with other slug-validated identifiers.
- **Mode:** Both.
- **Fix:** Add regex `^[A-Za-z0-9_-]{1,64}$`.

### M-8 — Numeric binary parsing in pg-wire protocol does not bound `ndigits`
- File: `gateway/dbt_proxy/protocol.py:315-331`
- `struct.unpack("!{ndigits}H")` will raise on truncation, but a maliciously crafted Bind value with very large `ndigits` causes an O(n) loop multiplying decimals — bounded by message length (1 MiB max) but still unnecessary CPU.
- **Mode:** Both.
- **Fix:** Reject `ndigits > 1000` (a real NUMERIC has at most ~131k digits in Postgres but `ndigits` of base-10000 limbs is small).

---

## High

(none in the changed code beyond the items above)

---

## Already mitigated (do NOT re-fix — covered by `tests/test_security_fixes.py`)

- V1: upstream errors sanitised, DSN never forwarded to client (`session.py:260-275`)
- V2: governance deny-list expanded (DO/LOAD/CREATE FUNCTION/PROC/TRIGGER/LANGUAGE/dblink/lo_*/pg_read_*/pg_ls_dir/SECURITY DEFINER/etc.)
- V3: server fails closed when `SP_GATEWAY_RUN_TOKEN_SECRET` is missing — no port bound
- V4: default bind host is `127.0.0.1`; `0.0.0.0` warns at startup
- V5: NUL bytes / NaN / Inf rejected in inline param substitution
- V6: audit-write failure raises `AuditWriteError` → ErrorResponse instead of executing un-audited
- Auth error sanitisation: protocol/password errors emit generic message + ref ID; org_id NOT logged in `auth_ok`

---

## Project ideology summary

| Issue | Required for localhost? | Cloud-only? |
|---|---|---|
| L-1 (mint log org leak) | yes | — |
| L-2 (scope_ref slug) | yes | — |
| L-3 (doc_id UUID validation) | yes | — |
| L-5 (debug log) | yes | — |
| L-6 (URL allowlist comment) | yes | — |
| L-8 (DATABASE_URL ssl probe) | — | yes |
| L-9 (force pending in cloud) | — | yes |
| M-1 (SQL identifier escaping in model_blueprint) | yes | — |
| M-2 (same in model_verify) | yes | — |
| M-3 (`_MODEL_NAME_RE`) | yes | — |
| M-4 (dbt prefix whitespace) | yes | — |
| M-5 (stdio cloud guard) | — | yes |
| M-6 (audit at-rest) | — | yes |
| M-7 (connector_name regex) | yes | — |
| M-8 (ndigits bound) | yes | — |
| I-2 (loopback bind for db port) | both — does not break dev | — |
| I-6 (TTL cap in cloud) | — | yes |
| I-1, I-3, I-4 | document only | — |
