# Sandbox container in `docker-compose.yml` adds `SYS_ADMIN`/`SYS_PTRACE` capabilities and disables AppArmor

**Status:** DEPRIORITIZED — feature disabled in cloud as of 2026-04-30; owner not actively maintaining. Severity rating retained to reflect technical risk; treat as low-priority until the feature is re-enabled.

- Slug: sandbox-container-runs-with-elevated-caps-and-no-apparmor
- Severity: Medium
- Cloud impact: Partial (compose file is the local stack; cloud deploys must not inherit these settings)
- Confidence: High
- Affected files / endpoints: `docker-compose.yml:71-86`

Back to [issues.md](issues.md)

---

## Problem

```yaml
# docker-compose.yml (sandbox service)
cap_add:
  - SYS_PTRACE
  - SYS_ADMIN
security_opt:
  - apparmor:unconfined
  - no-new-privileges:true
```

The sandbox service is granted two highly privileged Linux capabilities:

- `CAP_SYS_PTRACE` — allows tracing arbitrary processes; combined with read access to other pods' procfs, can dump memory of co-tenant containers on the same host.
- `CAP_SYS_ADMIN` — superset of many capabilities, often called "the new root." Required by gVisor's `runsc` rootless integration in some configurations, but it is the strongest capability a container can hold short of `--privileged`.

`apparmor:unconfined` removes the AppArmor profile that Docker normally applies to constrain syscalls outside the kernel's seccomp filter.

`no-new-privileges:true` is set, which is good. `read_only: true` is also set, which is good. `mem_limit: 512m`, `cpus: 2`, `pids_limit: 256` are set. These mitigations matter, but the capability grants undermine them: a sandboxed code escape that gains shell inside the container has more privileges than necessary.

The sandbox runs as root inside the container (Dockerfile.sandbox has no `USER` directive — see also finding 38 for the gateway). User code is supposed to run under gVisor, then drop to UID 65534 via `sandbox_exec.sh:setpriv`. But the parent process (the `sandbox_manager.py` aiohttp server) runs as root with `SYS_ADMIN`, meaning any RCE in the manager (e.g. via the unauthenticated `/execute` endpoint — finding 27) gives capabilities that gVisor was supposed to remove.

---

## Impact

- Defense-in-depth weakened: an attacker who breaks out of `runsc` (or who exploits the manager itself) inherits CAP_SYS_ADMIN and CAP_SYS_PTRACE.
- Container escape primitives (mount, ptrace, BPF) become available depending on the kernel and seccomp profile.
- Mounted host volumes (`/host-data:ro`) plus `SYS_ADMIN` reduces the cost of remount tricks.

---

## Exploit scenario

1. Attacker abuses the unauthenticated `/execute` on the sandbox manager (finding 27) to gain code execution in the manager process.
2. Manager runs as root with `SYS_ADMIN` and `SYS_PTRACE`.
3. Attacker uses `ptrace` to attach to neighboring container processes via shared host PID namespace (when not using PID isolation), or uses `SYS_ADMIN`-gated mount syscalls to read other tenants' bind-mounts.

This is a defense-in-depth finding; exploitation requires another bug. But the chain is short.

---

## Affected surface

- Files: `docker-compose.yml:71-86`, `Dockerfile.sandbox` (no `USER` directive).
- Auth modes: local docker-compose deployment; any cloud deploy that templates from compose.

---

## Proposed fix

- Drop `SYS_ADMIN` from `cap_add`. If it's required by `runsc` in some configs, prefer `runsc-rootless` or use `--platform=runc-with-userns`.
- Drop `SYS_PTRACE` unless a benchmark proves it's required.
- Replace `apparmor:unconfined` with a custom AppArmor profile generated from the runsc requirements; or simply remove the line and accept Docker's default profile.
- Add `USER 65534:65534` to `Dockerfile.sandbox` so the manager process itself runs unprivileged. The sandbox manager only needs to write under `/tmp` (already tmpfs) and make outbound HTTP calls.
- Document the threat model: sandbox container is a gVisor host, not a trust boundary by itself.

---

## Verification / test plan

- Unit: container start test (`docker run …`) with the new compose; assert the sandbox manager fails fast if it tries to call a privileged syscall.
- Manual: `docker exec sandbox sh -c 'cat /proc/self/status | grep Cap'` should show CapEff with no CAP_SYS_ADMIN.
- Manual: `docker exec sandbox apparmor_status` (from host) should show the sandbox under a non-`unconfined` profile.

---

## Rollout / migration notes

- Local-only change; no production cloud impact unless cloud deploys inherit from compose.
- Verify gVisor still functions for `execute_code` calls after capability drop.
- Rollback: re-add capabilities; non-destructive.
