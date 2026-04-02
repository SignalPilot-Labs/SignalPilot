# Python Backend Review Checklist

Scope: When diff contains `.py` files in `signalpilot/gateway/` or `self-improve/agent/`

---

## Async/Sync Mixing

The gateway is async-first (FastAPI). Sync I/O in async handlers blocks the event loop.

- Sync file I/O (`open()`, `json.load()`) called from async route handlers without `asyncio.to_thread()`
  - Known issue: `store.py` functions `_load_json`, `_save_json`, `load_settings` are sync — new code must not copy this pattern
  - Correct pattern: use `aiofiles` (as `store.py:append_audit` does) or `await asyncio.to_thread(sync_fn)`
- Sync database drivers called without `BaseConnector._run_in_thread()` wrapper
  - Postgres uses native async (`asyncpg`) — no wrapping needed
  - MySQL, MSSQL, Trino, ClickHouse use sync drivers — MUST use `_run_in_thread()`
- `time.sleep()` in async context — use `await asyncio.sleep()` instead
- Missing `await` on coroutine calls (results in a coroutine object, not the result)

## Pydantic Validation

Models live in `gateway/models.py` using Pydantic v2.

- New API endpoints accepting request bodies without a Pydantic model
- `Field()` constraints missing on user-facing inputs (e.g., `min_length`, `max_length`, `ge`, `le`)
- Using `model.dict()` (v1) instead of `model.model_dump()` (v2)
- Updates not using `model_dump(exclude_none=True)` — will overwrite fields with None
- Flat model anti-pattern: if adding fields to `ConnectionCreate`, verify they don't conflict across DB types

## Exception Handling

Error patterns are defined in `gateway/errors.py` and `api/deps.py`.

- Bare `except:` or `except Exception: pass` — must catch specific types and log
  - Known issue: `store.py:update_connection` has `except Exception: pass` on credential rebuild (line ~333)
- Database errors not passed through `sanitize_db_error()` before reaching the client
  - `sanitize_db_error()` in `api/deps.py` redacts credentials from error messages
- `HTTPException` raised without appropriate status code (400 for validation, 404 for not found, 408 for timeout)
- `asyncio.TimeoutError` not caught separately from generic exceptions in connector code
  - Correct pattern: see `api/query.py` which maps timeout to HTTP 408

## Connector Patterns

Connectors inherit from `BaseConnector` in `connectors/base.py`.

- New connectors missing `execute()`, `get_schema()`, `health_check()` implementations
- Schema queries using f-string interpolation instead of `self._quote_identifier()` / `self._quote_table()`
- Missing registration in `connectors/registry.py`
- `health_check()` that raises instead of returning `False` on failure (base class pattern swallows exceptions)
- SSL temp files not cleaned up — use `_write_ssl_files()` / cleanup in `disconnect()`
- Connection pool created per query instead of reused — check for pool lifecycle management

## Credential & Secret Safety

Credentials are managed in `store.py` with Fernet encryption.

- Passwords, tokens, or connection strings logged in error messages or debug output
- Sensitive fields not stripped before persisting to `connections.json`
- New credential fields not added to the Fernet vault (`_credential_vault`)
- `SP_ENCRYPTION_KEY` or derived keys appearing in any non-store module

## Self-Improve Agent Patterns

Agent code in `self-improve/agent/` uses `aiosqlite`.

- New tool permissions not added to `permissions.py:check_tool_permission()`
- Database writes missing `await conn.commit()` after `execute()`
- Hook functions that raise on failure instead of logging (hooks must never block tool execution)
- `_safe_serialize()` not used on large data before DB insertion (2000 char truncation)
