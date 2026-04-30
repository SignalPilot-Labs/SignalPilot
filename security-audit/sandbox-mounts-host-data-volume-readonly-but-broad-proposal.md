# Sandbox container mounts `${HOST_DATA_DIR:-~}:/host-data:ro` — entire user home by default

- Slug: sandbox-mounts-host-data-volume-readonly-but-broad
- Severity: Medium
- Cloud impact: Partial
- Confidence: High
- Affected files / endpoints: `docker-compose.yml:85`

Back to [issues.md](issues.md)

---

## Problem

The sandbox container in Docker Compose mounts the operator's home directory by default:

```yaml
# docker-compose.yml:85
volumes:
  - ${HOST_DATA_DIR:-~}:/host-data:ro
```

When `HOST_DATA_DIR` is unset, this mounts `~` (the operator's home directory) read-only into every sandbox container at `/host-data`. Every sandbox spawned by the sandbox manager can then read:

- `.ssh/` (SSH private keys)
- `.aws/` (AWS credentials)
- `.gitconfig`, `.npmrc`, `.pypirc` (API tokens, credentials)
- Any file in the home directory, including application configs, SSL certificates, or secret files

The mount is read-only, which prevents writes, but read access to the entire home directory is an extremely broad attack surface. A sandboxed Python execution (even within gVisor) could read any of these files:

```python
# Code executed inside sandbox
with open('/host-data/.ssh/id_rsa', 'r') as f:
    print(f.read())  # Exfiltrates SSH private key
```

In cloud mode, sandbox is disabled (`main.py:87`). However, this default affects all local operators and any enterprise deployment using Docker Compose without customizing `HOST_DATA_DIR`.

---

## Impact

- **Local mode:** Sandbox executions can read all files in the operator's home directory, including credentials files (`.aws/credentials`, `.ssh/id_rsa`, `.npmrc`).
- **Cloud mode:** Not directly exploitable (sandbox disabled), but if sandbox is re-enabled in cloud, the volume mount must be explicitly restricted.
- **Enterprise on-premises:** Any Docker Compose-based deployment without `HOST_DATA_DIR` set is affected.

---

## Exploit scenario

1. Local operator runs SignalPilot with Docker Compose without setting `HOST_DATA_DIR`.
2. User creates a sandbox via the UI.
3. User (or attacker who has the user's API key) executes in the sandbox:

```python
import os
import subprocess

# List home directory:
files = os.listdir('/host-data')
print(files)  # Shows .ssh, .aws, .gitconfig, etc.

# Read AWS credentials:
with open('/host-data/.aws/credentials', 'r') as f:
    print(f.read())
```

4. Attacker receives the operator's AWS credentials via the sandbox execution output.

Note: this is the operator's own machine, so in a single-user local setup the operator is the attacker. In a shared local deployment (multiple users on the same host) or an enterprise deployment where the gateway runs with a privileged user account, this is a cross-user attack.

---

## Affected surface

- Files: `docker-compose.yml:85`
- Endpoints: `POST /api/sandboxes/{id}/execute`
- Auth modes: Local mode (cloud sandbox disabled)

---

## Proposed fix

1. **Change the default to a dedicated, empty volume:**

```yaml
# docker-compose.yml:
volumes:
  - ${HOST_DATA_DIR:-/srv/signalpilot-sandbox-data}:/host-data:ro
```

Create a named volume or a dedicated directory in the compose file:

```yaml
volumes:
  signalpilot-sandbox-data:
    driver: local

services:
  sandbox:
    volumes:
      - signalpilot-sandbox-data:/host-data:ro
```

Users who want to mount specific files for sandbox access can set `HOST_DATA_DIR` explicitly to a narrow directory (e.g., `/path/to/data-exports`).

2. **Add a warning comment** in `docker-compose.yml`:

```yaml
# HOST_DATA_DIR: directory to expose to sandbox for file access.
# WARNING: The sandbox can READ all files in this directory.
# Do NOT point to your home directory or any directory with credentials.
# Default: /srv/signalpilot-sandbox-data (empty volume)
```

3. **In cloud mode, remove the mount entirely** via a cloud-specific docker-compose override:

```yaml
# docker-compose.prod.yml:
services:
  sandbox:
    volumes: []  # No host-data mount in cloud
```

---

## Verification / test plan

**Manual checklist:**
- Start sandbox with default `HOST_DATA_DIR` unset.
- Execute `os.listdir('/host-data')` in sandbox.
- Before fix: lists home directory contents. After fix: empty directory or only intended data files.

---

## Rollout / migration notes

- **Breaking change for users relying on the default:** Users who mount local DuckDB/SQLite files via the file browser will need to set `HOST_DATA_DIR` explicitly.
- Document the change prominently in the release notes.
- Provide a migration guide: "Set `HOST_DATA_DIR=/path/to/your/data` to restore file browser access."
- Rollback: revert `${HOST_DATA_DIR:-~}` default.
