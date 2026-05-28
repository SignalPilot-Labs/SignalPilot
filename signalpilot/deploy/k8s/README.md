# SignalPilot Kubernetes Deployment

## Overview

This directory contains Kubernetes deployment configuration for SignalPilot.
Notebook pods run in per-org namespaces with NetworkPolicy isolation (Round 3).
Workspace files are persisted via S3 (or local FS in dev) by the gateway (Round 4).

---

## S3 Workspace Persistence

### Architecture

The gateway is the **only** component holding S3 credentials. Notebook pods are
credential-less. The gateway hydrates `/workspace` before the notebook server starts, and
snapshots it periodically and on pod delete via `pods/exec tar`.

**S3 prefix layout:**

```
s3://<bucket>/<prefix_root>/
  org/<org_id>/
    user/<user_id>/
      notebook/<notebook_id>/
        snapshots/<manifest_version>/
          <relpath/of/file>
        _manifest.current.json    <- pointer: {"version":"...","file_count":N,...}
```

`notebook_id` is derived as:
```
sha256(f"{org_id}:{user_id}:{project_id or ''}".encode()).hexdigest()[:32]
```

**Orphan-on-rename note (C3):** `notebook_id` is keyed on `(org_id, user_id,
project_id)` only. If `project_id` is renamed or changed, the new session gets
a new `notebook_id` and the old S3 prefix persists unused. GC of orphaned
prefixes is planned for Round 6.

**Branch-switch note:** `branch` is **not** part of `notebook_id`. Switching
branches within a session sees the same workspace contents as before the switch.
In-session branch switching is unsupported in Round 4. The branch value is
stored as metadata on the session row but does not affect storage identity.

**Concurrent sessions (last-writer-wins):** Two sessions with the same
`notebook_id` (e.g. two browser tabs) each write snapshots independently.
Every `_manifest.current.json` is guaranteed to point to a complete file tree,
but the last snapshot to complete wins the pointer. Merging is planned for R6.

### IAM Policy

Attach the following IAM policy to the gateway service account (IRSA or pod
identity). Replace `<bucket>` and `<prefix_root>` with your values.

```json
{
  "Version": "2012-10-17",
  "Statement": [
    {
      "Effect": "Allow",
      "Action": ["s3:ListBucket"],
      "Resource": "arn:aws:s3:::<bucket>",
      "Condition": {
        "StringLike": {
          "s3:prefix": ["<prefix_root>/*"]
        }
      }
    },
    {
      "Effect": "Allow",
      "Action": ["s3:GetObject", "s3:PutObject", "s3:DeleteObject"],
      "Resource": "arn:aws:s3:::<bucket>/<prefix_root>/*"
    }
  ]
}
```

**IRSA note:** To use IAM Roles for Service Accounts (IRSA), annotate the
gateway `ServiceAccount` with:
```yaml
metadata:
  annotations:
    eks.amazonaws.com/role-arn: arn:aws:iam::<account-id>:role/<role-name>
```
Full IRSA bootstrap documentation is planned for Round 6. In the meantime,
set `AWS_ACCESS_KEY_ID` / `AWS_SECRET_ACCESS_KEY` directly in the gateway
deployment's environment (not in pod specs — pods must remain credential-less).

### SP_WORKSPACE_* Environment Variables

| Variable | Default | Description |
|---|---|---|
| `SP_WORKSPACE_BACKEND` | `disabled` | `s3`, `local`, or `disabled`. **Must not be `disabled` in cloud mode.** |
| `SP_WORKSPACE_S3_BUCKET` | — | S3 bucket name. Required when backend=s3. |
| `SP_WORKSPACE_S3_REGION` | — | AWS region. Required when backend=s3. |
| `SP_WORKSPACE_S3_ENDPOINT_URL` | — | Override endpoint (MinIO, LocalStack). Optional. |
| `SP_WORKSPACE_S3_PREFIX_ROOT` | `workspaces/v1` | S3 key prefix root. Must match `^[a-z0-9][a-z0-9/_-]*[a-z0-9]$`. No `..`. |
| `SP_WORKSPACE_LOCAL_ROOT` | — | Filesystem root for local backend. Required when backend=local. |
| `SP_WORKSPACE_SNAPSHOT_INTERVAL_SECONDS` | `60` | Periodic snapshot interval (30–3600 s). |
| `SP_WORKSPACE_MAX_FILE_BYTES` | `104857600` | Max file size (100 MiB). Larger files are skipped. |
| `SP_WORKSPACE_HYDRATE_TIMEOUT_SECONDS` | `60` | Max time to hydrate `/workspace` before 503. |
| `SP_WORKSPACE_SHUTDOWN_DRAIN_SECONDS` | `30` | Time budget for final snapshots on gateway shutdown (max 120 s). |
| `SP_WORKSPACE_TMP_ROOT` | system temp | Root for gateway-side temp dirs. Set to a fast local volume. |

### MinIO Dev Recipe

For local development with a MinIO instance:

```bash
# Start MinIO
docker run -d \
  -p 9000:9000 -p 9001:9001 \
  -e MINIO_ROOT_USER=minioadmin \
  -e MINIO_ROOT_PASSWORD=minioadmin \
  --name minio \
  quay.io/minio/minio server /data --console-address ":9001"

# Create bucket
docker exec minio mc alias set local http://localhost:9000 minioadmin minioadmin
docker exec minio mc mb local/signalpilot-dev
```

Gateway env vars for MinIO:
```
SP_WORKSPACE_BACKEND=s3
SP_WORKSPACE_S3_BUCKET=signalpilot-dev
SP_WORKSPACE_S3_REGION=us-east-1
SP_WORKSPACE_S3_ENDPOINT_URL=http://localhost:9000
AWS_ACCESS_KEY_ID=minioadmin
AWS_SECRET_ACCESS_KEY=minioadmin
```

### Local FS Backend (dev / single-node)

```
SP_WORKSPACE_BACKEND=local
SP_WORKSPACE_LOCAL_ROOT=/var/signalpilot/workspaces
```

The local backend uses `os.replace` for atomic pointer updates. Safe for
single-process gateway deployments. Not suitable for multi-replica gateways
(use S3 instead).

---

## pods/exec RBAC

Each org namespace receives a `Role` with `pods/exec create`. This is required
for the gateway to hydrate and snapshot notebook pods via `tar`. The exec
surface is locked down at the application boundary:

- Only `orchestrator/pod_exec_io.py` calls `pods/exec` (enforced by CI AST test).
- Container name is hardcoded to `notebook`.
- All `src_path`/`dest_path` values are validated to start with `/workspace/`.
- The argv passed to tar is a Python list literal, never constructed via string interpolation.

---

## Environment Variables Reference (gateway)

See also `signalpilot/gateway/gateway/config/` for all settings classes.

| Variable | Default | Description |
|---|---|---|
| `SP_DEPLOYMENT_MODE` | `local` | `local` or `cloud`. Cloud mode enforces stricter security. |
| `SP_NOTEBOOK_IMAGE` | `signalpilot-notebook:latest` | Notebook pod image. |
| `SP_PUBLIC_GATEWAY_URL` | — | Public gateway URL for pod JWT callbacks. Required in cloud mode. |
| `SP_SESSION_JWT_TTL_SECONDS` | `3600` | TTL for notebook session JWTs. |
