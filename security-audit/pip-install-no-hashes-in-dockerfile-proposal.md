# Dockerfile.gateway runs `pip install --no-cache-dir -e .` then a second pip install with no `--require-hashes`

- Slug: pip-install-no-hashes-in-dockerfile
- Severity: Low
- Cloud impact: Yes
- Confidence: High
- Affected files / endpoints: `Dockerfile.gateway:9-18`

Back to [issues.md](issues.md)

---

## Problem

The gateway Dockerfile installs Python dependencies without hash verification:

```dockerfile
# Dockerfile.gateway:9-18
RUN pip install --no-cache-dir -e . && \
    pip install --no-cache-dir \
    duckdb \
    "clickhouse-driver==0.2.7" \
    clickhouse-connect \
    "sshtunnel==0.4.0" \
    "cryptography==44.0.0" \
    "snowflake-connector-python>=3.12.0,<4" \
    "google-cloud-bigquery==3.20.0" \
    pyarrow
```

Without `--require-hashes`, pip resolves dependencies at build time and accepts any package from PyPI that matches the version specifier. Problems:

1. **Supply-chain attack surface:** If PyPI is compromised or a maintainer's account is hijacked, a malicious version of `duckdb`, `snowflake-connector-python`, or `cryptography` could be served to the build process. With version specifiers (`>=3.12.0,<4`), pip accepts any version in the range — including a new malicious version.
2. **No reproducible builds:** Different builds may install different package versions (within specifiers), making it impossible to audit exactly what shipped.
3. **`--no-cache-dir` does not provide hash verification.** It only prevents caching; it does not verify the downloaded wheel's integrity.
4. **`pyproject.toml` dependencies are installed with `-e .`** (editable install), which also lacks hash pinning.

The `cryptography` package handles all Fernet encryption in the gateway. A malicious version of `cryptography` could exfiltrate encryption keys.

---

## Impact

- Supply-chain attack on a critical package (e.g., `cryptography`, `snowflake-connector-python`) leads to complete credential exfiltration or RCE in the gateway container.
- The `cryptography` package has direct access to `SP_ENCRYPTION_KEY` and all decrypted credentials.
- Low current probability (PyPI is generally secure), but high impact if exploited.

---

## Exploit scenario

1. Attacker compromises a PyPI maintainer account for `cryptography`.
2. Attacker publishes `cryptography==44.0.1` (patched to include a backdoor that sends `SP_ENCRYPTION_KEY` to an external server).
3. SignalPilot gateway Docker image is rebuilt with `"cryptography==44.0.0"` pinned — but `pip install --no-cache-dir` may update to `44.0.1` if the specifier allows it. (In this case it's pinned to `44.0.0` exactly — but `duckdb`, `pyarrow`, `clickhouse-connect` without pins are vulnerable.)
4. New gateway image ships with the malicious package.
5. Attacker receives `SP_ENCRYPTION_KEY` from every gateway instance that updates.

---

## Affected surface

- Files: `Dockerfile.gateway:9-18`
- Endpoints: Gateway container build process (supply chain)
- Auth modes: All modes

---

## Proposed fix

Generate a `requirements.lock` file with exact versions and hashes, then use it in the Dockerfile:

```bash
# Generate lock file (run locally, commit to repo):
pip-compile pyproject.toml --generate-hashes --output-file requirements.lock

# For additional packages:
pip-compile additional-requirements.in --generate-hashes --output-file additional.lock
```

```dockerfile
# Dockerfile.gateway — updated:
FROM python:3.12-slim

WORKDIR /app
COPY pyproject.toml requirements.lock additional.lock ./
COPY gateway/ gateway/

# Install from lock file with hash verification
RUN pip install --no-cache-dir --require-hashes -r requirements.lock && \
    pip install --no-cache-dir --require-hashes -r additional.lock

EXPOSE 3300
CMD ["uvicorn", "gateway.main:app", "--host", "0.0.0.0", "--port", "3300"]
```

The `requirements.lock` file should be committed to the repository and reviewed in PRs for any version changes.

**Alternative:** Use `pip-audit` as a CI step to detect known vulnerabilities in installed packages.

---

## Verification / test plan

**CI step:**
```bash
pip-audit --requirement requirements.lock
```

**Build verification:**
```bash
# Build with --require-hashes:
docker build --no-cache -t signalpilot-gateway .
# Should fail if any package hash does not match
```

---

## Rollout / migration notes

- Generate `requirements.lock` from the current `pyproject.toml` and commit it.
- The lock file must be updated whenever a dependency version changes (via a dedicated PR).
- Consider using `renovate` or `dependabot` for automated lock file updates.
- Rollback: revert to the current `pip install` command without `--require-hashes`.
