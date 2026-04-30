# `_create_new_project` writes credentials into `profiles.yml` on disk

**Status:** DEPRIORITIZED — feature disabled in cloud as of 2026-04-30; owner not actively maintaining. Severity rating retained to reflect technical risk; treat as low-priority until the feature is re-enabled.

- Slug: dbt-profiles-yml-written-with-plaintext-credentials
- Severity: Medium
- Cloud impact: Partial
- Confidence: High
- Affected files / endpoints: `signalpilot/gateway/gateway/store.py:1116-1135,1155-1173`

Back to [issues.md](issues.md)

---

## Problem

`_create_new_project` writes warehouse credentials (host, port, database, username, password) as plaintext into a `profiles.yml` file on disk:

```python
# store.py:1116-1135,1155-1173 (approximate offsets)
profiles_path = project_dir / "profiles.yml"
profiles_content = yaml.dump({
    "signalpilot": {
        "target": "dev",
        "outputs": {
            "dev": {
                "type": conn.db_type,
                "host": conn.host,
                "port": conn.port,
                "database": conn.database,
                "user": conn.username,
                "password": conn.password,  # plaintext on disk
                ...
            }
        }
    }
})
profiles_path.write_text(profiles_content)
```

`main.py:87` logs "sandbox disabled in cloud" and notes dbt projects are disabled, but the code path is still present and active. If cloud mode ever re-enables dbt projects (even temporarily for debugging or enterprise features), plaintext warehouse credentials land in `/data` on every gateway pod.

The `/data` volume in the Kubernetes/cloud deployment may be:
- A shared PVC accessible to other pods.
- An NFS mount that is snapshotted or backed up without encryption.
- Readable by a compromised sidecar container.

Even in local mode (Docker Compose), the file is created on the host volume, which is world-readable by default on many Linux configurations.

---

## Impact

- **Cloud (if re-enabled):** Plaintext credentials for every connected warehouse are written to disk. Any process with filesystem access to `/data/projects/` can read all credentials without decryption.
- **Local mode (current):** Credentials written to `~/.signalpilot/projects/*/profiles.yml`. This is a known dbt pattern, but the files should be group/world-read restricted.
- **Audit trail gap:** Unlike the encrypted DB columns, `profiles.yml` writes are not logged.

---

## Exploit scenario

**Cloud — if dbt re-enabled:**
1. Admin enables dbt projects feature in cloud mode.
2. User creates a dbt project for their Postgres connection.
3. `_create_new_project` writes `profiles.yml` with plaintext password to `/data/projects/acme/profiles.yml`.
4. Attacker with read access to the data volume (e.g., a compromised pod with volume mount) reads the file:

```bash
cat /data/projects/acme/profiles.yml
# outputs: host: prod.acme.com, password: supersecret
```

5. Attacker has plaintext warehouse credentials.

---

## Affected surface

- Files: `signalpilot/gateway/gateway/store.py:1116-1135,1155-1173`
- Endpoints: `POST /api/projects` (dbt project creation)
- Auth modes: Local mode (current); cloud if re-enabled

---

## Proposed fix

1. **In cloud mode, raise immediately:**

```python
# store.py:_create_new_project:
from .deployment import is_cloud_mode

async def _create_new_project(self, ...):
    if is_cloud_mode():
        raise ValueError("dbt projects are not supported in cloud mode")
    ...
```

2. **Never write plaintext credentials.** Use dbt env var indirection instead:

```yaml
# profiles.yml — use env vars, not inline secrets:
signalpilot:
  target: dev
  outputs:
    dev:
      type: postgres
      host: "{{ env_var('SP_DBT_HOST') }}"
      port: "{{ env_var('SP_DBT_PORT') | int }}"
      database: "{{ env_var('SP_DBT_DATABASE') }}"
      user: "{{ env_var('SP_DBT_USER') }}"
      password: "{{ env_var('SP_DBT_PASSWORD') }}"
```

Write a `.env` file for the dbt process with restrictive permissions (mode 0600), or inject via process environment.

3. **Set restrictive file permissions on `profiles.yml`:**

```python
profiles_path.write_text(profiles_content)
profiles_path.chmod(0o600)  # owner-only read
```

---

## Verification / test plan

**Unit tests:**
1. `test_create_project_cloud_mode_raises` — mock `is_cloud_mode=True`, call `_create_new_project`, assert `ValueError`.
2. `test_profiles_yml_no_plaintext_password` — in local mode, assert `profiles.yml` content contains `env_var('SP_DBT_PASSWORD')` not the actual password.
3. `test_profiles_yml_permissions` — assert `profiles_path` has mode `0o600`.

---

## Rollout / migration notes

- **Cloud:** The cloud guard is a one-line change; already effectively disabled by the log message in `main.py:87`. Make it a hard exception.
- **Local:** Env var indirection requires updating how the dbt subprocess is launched (pass env vars to the subprocess). This is a more involved change.
- **Existing `profiles.yml` files on disk:** A migration script should find and delete or re-generate them with env var indirection.
- Rollback: remove the `is_cloud_mode()` guard; restore plaintext writes (not recommended).
