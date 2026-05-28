# SignalPilot Kubernetes Deployment

## Overview

This directory contains Kubernetes deployment configuration for SignalPilot.
Notebook pods run in per-org namespaces with NetworkPolicy isolation (Round 3).

---

## Workspace Storage

Workspaces are git-backed. Each notebook pod's entrypoint clones the
project's bare git repository (managed by the gateway, mirrored from
GitHub) into `/workspace` before starting `sp edit`. Changes are pushed
back over the same channel. Pod-local state is ephemeral; durability
lives in git.

---

## pods/exec RBAC

Each org namespace receives a `Role` with `pods/exec create`. This is required
for the gateway to execute commands in notebook pods. The exec surface is
locked down at the application boundary:

- Only `orchestrator/pod_exec_io.py` calls `pods/exec` (enforced by CI AST test).
- Container name is hardcoded to `notebook`.

---

## Environment Variables Reference (gateway)

See also `signalpilot/gateway/gateway/config/` for all settings classes.

| Variable | Default | Description |
|---|---|---|
| `SP_DEPLOYMENT_MODE` | `local` | `local` or `cloud`. Cloud mode enforces stricter security. |
| `SP_NOTEBOOK_IMAGE` | `signalpilot-notebook:latest` | Notebook pod image. |
| `SP_PUBLIC_GATEWAY_URL` | — | Public gateway URL for pod JWT callbacks. Required in cloud mode. |
| `SP_SESSION_JWT_TTL_SECONDS` | `3600` | TTL for notebook session JWTs. |
