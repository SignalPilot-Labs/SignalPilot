# `allowed_exts` check in `sandbox_manager.py` uses `resolved.suffix.lower()` — `.tar.gz` classified as `.gz`

**Status:** DEPRIORITIZED — feature disabled in cloud as of 2026-04-30; owner not actively maintaining. Severity rating retained to reflect technical risk; treat as low-priority until the feature is re-enabled.

- Slug: sandbox-mount-extension-allowlist-trivially-bypassed
- Severity: Low
- Cloud impact: Partial
- Confidence: High
- Affected files / endpoints: `sp-sandbox/sandbox_manager.py:171-178`

Back to [issues.md](issues.md)

---

## Problem

The file mount extension allowlist in the sandbox manager uses Python's `Path.suffix` which only returns the last extension:

```python
# sandbox_manager.py:171-178
allowed_exts = {".duckdb", ".db", ".sqlite", ".sqlite3", ".parquet", ".csv", ".json"}
if resolved.suffix.lower() not in allowed_exts:
    return web.json_response(
        {"success": False, "error": f"File type not allowed: {resolved.suffix}"},
        status=400,
    )
```

`Path("data.tar.gz").suffix` returns `".gz"`, not `".tar.gz"`. This means:
- `database.csv.gz` → suffix is `.gz` → blocked (correct, `.gz` not in allowlist).
- `exploit.duckdb.sh` → suffix is `.sh` → blocked (correct).
- `exploit.sh.duckdb` → suffix is `.duckdb` → ALLOWED (incorrect — this is a shell script with a misleading extension).

An attacker who can place a file named `malicious.sh.duckdb` on the host data volume could mount it into the sandbox and read it as a DuckDB database. DuckDB's parser would reject it (not a valid DB file), but it could exfiltrate the file contents via error messages or by reading it as a text file.

Additionally, the allowlist does not cover `.gz`, `.zip`, `.tar` (compressed archives) — a `data.gz` file cannot be mounted, but this is correct since the allowlist is designed for data files, not archives. The larger concern is the `{name}.allowed_ext` bypass above.

---

## Impact

- An attacker who controls the file name (e.g., via a file upload feature, or by placing files in the data directory) can give a script a `.duckdb` extension and have it mounted into the sandbox.
- Inside the sandbox, the "DuckDB file" is read by the Python execution environment. The attacker can read its contents and exfiltrate them via `print()`.
- Risk is low because the sandbox is gVisor-isolated and the attacker needs write access to the host data directory.

---

## Exploit scenario

1. Attacker places `/host-data/secret.sh.duckdb` (containing bash script) in the host data directory.
2. Attacker requests sandbox execution with `file_mounts: [{"host_path": "/host-data/secret.sh.duckdb", "sandbox_path": "mydb"}]`.
3. Extension check: `Path("secret.sh.duckdb").suffix` = `.duckdb` → allowed.
4. File is mounted into sandbox at `/mydb`.
5. Sandbox code:
```python
with open('/mydb', 'r') as f:
    print(f.read())  # Exfiltrates script contents
```

---

## Affected surface

- Files: `sp-sandbox/sandbox_manager.py:171-178`
- Endpoints: `POST /execute` (file_mounts parameter)
- Auth modes: Local mode (sandbox disabled in cloud)

---

## Proposed fix

Use `Path.suffixes` to check all extensions, and reject files with multiple extensions where the outer extension is in the allowlist:

```python
# sandbox_manager.py — updated extension check:
allowed_exts = {".duckdb", ".db", ".sqlite", ".sqlite3", ".parquet", ".csv", ".json"}
blocked_exts = {".sh", ".py", ".exe", ".bat", ".cmd", ".bash", ".zsh", ".fish", ".pl", ".rb"}

suffixes = resolved.suffixes  # e.g., [".sh", ".duckdb"] for "file.sh.duckdb"
if len(suffixes) > 1:
    # Reject files with multiple extensions — too risky
    return web.json_response(
        {"success": False, "error": "Files with multiple extensions are not allowed"},
        status=400,
    )
if not suffixes or suffixes[0].lower() not in allowed_exts:
    return web.json_response(
        {"success": False, "error": f"File type not allowed: {resolved.suffix}"},
        status=400,
    )
# Additional: check for blocked inner extension
for s in suffixes:
    if s.lower() in blocked_exts:
        return web.json_response(
            {"success": False, "error": f"File type not allowed: {s}"},
            status=400,
        )
```

Optionally, add magic-byte verification for DuckDB files (DuckDB files start with `DUCK`):

```python
# Verify magic bytes for binary formats:
MAGIC_BYTES = {
    ".duckdb": b"DUCK",
    ".sqlite": b"SQLite format 3\x00",
    ".sqlite3": b"SQLite format 3\x00",
}
suffix = resolved.suffix.lower()
if suffix in MAGIC_BYTES:
    with open(resolved, "rb") as f:
        header = f.read(16)
    if not header.startswith(MAGIC_BYTES[suffix]):
        return web.json_response(
            {"success": False, "error": "File content does not match declared type"},
            status=400,
        )
```

---

## Verification / test plan

**Unit tests:**
1. `test_double_extension_blocked` — path `file.sh.duckdb`, assert 400.
2. `test_single_allowed_extension_ok` — path `data.duckdb`, assert allowed.
3. `test_magic_bytes_mismatch_blocked` — DuckDB path but file contains text, assert 400.

---

## Rollout / migration notes

- No data migration.
- The double-extension block may affect users who have files with multiple extensions. Document the restriction.
- Rollback: revert to `resolved.suffix.lower()` check.
