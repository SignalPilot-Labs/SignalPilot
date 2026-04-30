# `Dockerfile.gateway` runs `uvicorn` as UID 0 (root)

- Slug: dockerfile-gateway-runs-as-root
- Severity: Medium
- Cloud impact: Yes
- Confidence: High
- Affected files / endpoints: `Dockerfile.gateway` (no `USER` directive)

Back to [issues.md](issues.md)

---

## Problem

`Dockerfile.gateway` has no `USER` directive, so the gateway process runs as root (UID 0):

```dockerfile
# Dockerfile.gateway:
FROM python:3.12-slim
WORKDIR /app
COPY pyproject.toml .
COPY gateway/ gateway/
RUN pip install --no-cache-dir -e . && ...
EXPOSE 3300
CMD ["uvicorn", "gateway.main:app", "--host", "0.0.0.0", "--port", "3300"]
# No USER directive — runs as root
```

Running application processes as root inside a container provides no defense against:
1. **Container escape:** If a vulnerability in uvicorn, Python, or a gateway dependency allows code execution, the attacker has root inside the container. Combined with any container escape (kernel vulnerability, misconfigured `securityContext`, etc.), the attacker gains root on the host.
2. **Privilege escalation via capability abuse:** Root processes inside containers retain default capabilities (`CAP_NET_BIND_SERVICE`, `CAP_DAC_OVERRIDE`, etc.). A process-level vulnerability can use these capabilities before the attacker reaches the host.
3. **Volume permission abuse:** Root inside the container can modify files owned by root in mounted volumes, even with `read-only` filesystem settings outside the volume mounts.

The sandbox container (`Dockerfile.sandbox`) has the same issue — it runs `python3 sandbox_manager.py` as root.

---

## Impact

- Root inside the container → easier exploitation of container escape vulnerabilities.
- Root can write to any world-writable directory in the container filesystem.
- Root can read any file in mounted volumes, including the `/data` volume with encrypted credentials and the `/shared` volume with the local API key.

---

## Exploit scenario

1. Python deserialization vulnerability (hypothetical) in a dependency allows RCE inside the gateway container.
2. Attacker has a shell as root inside the container.
3. Attacker reads the `/data/local_api_key` file (accessible to root).
4. Attacker uses the API key for persistent access.
5. If a container escape is available (CVE in the kernel or container runtime), root privilege makes the escape easier.

---

## Affected surface

- Files: `Dockerfile.gateway`, `Dockerfile.sandbox` (by analogy)
- Endpoints: All gateway endpoints (the running process context)
- Auth modes: Cloud and local

---

## Proposed fix

Add a non-root user to both Dockerfiles:

```dockerfile
# Dockerfile.gateway — updated:
FROM python:3.12-slim

# Create a non-root user
RUN groupadd -g 10001 appuser && \
    useradd -r -u 10001 -g appuser appuser

WORKDIR /app

COPY pyproject.toml .
COPY gateway/ gateway/

RUN pip install --no-cache-dir -e . && \
    pip install --no-cache-dir \
    duckdb clickhouse-driver clickhouse-connect sshtunnel \
    "cryptography==44.0.0" \
    "snowflake-connector-python>=3.12.0,<4" \
    "google-cloud-bigquery==3.20.0" \
    pyarrow

# Ensure the data directory is writable by appuser
RUN mkdir -p /data && chown -R appuser:appuser /data

USER appuser

EXPOSE 3300
CMD ["uvicorn", "gateway.main:app", "--host", "0.0.0.0", "--port", "3300"]
```

Similarly for `Dockerfile.sandbox`:

```dockerfile
# Dockerfile.sandbox — add:
RUN groupadd -g 10001 appuser && \
    useradd -r -u 10001 -g appuser appuser
USER appuser
```

In Kubernetes deployments, additionally set:

```yaml
securityContext:
  runAsNonRoot: true
  runAsUser: 10001
  readOnlyRootFilesystem: true
  allowPrivilegeEscalation: false
  capabilities:
    drop: ["ALL"]
```

---

## Verification / test plan

**Unit tests:**
1. Build the Docker image and run: `docker run --rm signalpilot-gateway id` — assert output contains `uid=10001(appuser)`, not `uid=0(root)`.

**Manual checklist:**
- `docker run --rm signalpilot-gateway id`
- Before fix: `uid=0(root) gid=0(root)`.
- After fix: `uid=10001(appuser) gid=10001(appuser)`.

---

## Rollout / migration notes

- **Volume permissions:** The `/data` volume must be owned by UID 10001. On first deploy with the new image, run `chown -R 10001:10001 /data` if the volume already exists.
- **Port binding:** Ports above 1024 do not require root. Port 3300 is fine.
- **Package installation:** The `RUN pip install` step must run before `USER appuser` (installation requires write to system directories).
- Rollback: remove `USER appuser` directive.
