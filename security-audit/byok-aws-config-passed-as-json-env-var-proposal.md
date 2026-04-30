# `SP_BYOK_PROVIDER_CONFIG` is JSON env var that may contain AWS access key

- Slug: byok-aws-config-passed-as-json-env-var
- Severity: Low
- Cloud impact: Yes
- Confidence: High
- Affected files / endpoints: `signalpilot/gateway/gateway/main.py:64-72`

Back to [issues.md](issues.md)

---

## Problem

The BYOK provider configuration — which may include AWS IAM credentials — is passed as a JSON string in an environment variable:

```python
# main.py:64-72
byok_provider_type = os.getenv("SP_BYOK_PROVIDER", "local")
byok_provider_config_raw = os.getenv("SP_BYOK_PROVIDER_CONFIG")
byok_provider_config: dict | None = None
if byok_provider_config_raw:
    import json as _json
    try:
        byok_provider_config = _json.loads(byok_provider_config_raw)
    except _json.JSONDecodeError:
        logger.error("STARTUP FATAL: SP_BYOK_PROVIDER_CONFIG contains invalid JSON")
        raise SystemExit(1)
```

If `SP_BYOK_PROVIDER=aws_kms`, the `SP_BYOK_PROVIDER_CONFIG` JSON may contain:
```json
{"aws_access_key_id": "AKIAIOSFODNN7EXAMPLE", "aws_secret_access_key": "wJalrXUtnFEMI/..."}
```

Putting AWS credentials in an environment variable is technically acceptable but represents a lower-security approach compared to:
1. **IAM instance roles / IRSA** (IAM Roles for Service Accounts in EKS) — credentials are rotated automatically and never appear in process environment.
2. **AWS Secrets Manager** — the secret is fetched at runtime, not baked into the deployment config.

Problems:
1. **Credential in environment is visible** via `ps auxwwe`, `/proc/{pid}/environ`, debug logging of env vars, container inspection (`docker inspect`), and K8s deployment manifests stored in etcd.
2. **No automatic rotation.** Static IAM credentials require manual rotation. Long-lived credentials are higher risk.
3. **No least-privilege signal.** The presence of raw credentials in config suggests the deployment guide may not emphasize IRSA, leading operators to use long-lived IAM user credentials instead.

---

## Impact

- AWS credentials in `SP_BYOK_PROVIDER_CONFIG` exposed via process environment introspection.
- In Kubernetes: credentials may be visible in the pod spec, which is stored in etcd.
- Long-lived static credentials mean a credential leak has indefinite validity until manually rotated.

---

## Exploit scenario

1. Attacker exploits a vulnerability in the gateway that allows reading `/proc/self/environ` (e.g., via a path traversal in a file browser endpoint).
2. Reads `SP_BYOK_PROVIDER_CONFIG={"aws_access_key_id":"AKIA...","aws_secret_access_key":"..."}`.
3. Uses these credentials to access the KMS key directly, decrypting all BYOK-protected credentials.

---

## Affected surface

- Files: `signalpilot/gateway/gateway/main.py:64-72`
- Endpoints: Gateway startup configuration
- Auth modes: Cloud mode (where BYOK with cloud KMS is used)

---

## Proposed fix

1. **Document IRSA setup as the recommended approach** in the deployment guide:

```markdown
# Recommended: IRSA (IAM Roles for Service Accounts)
# No credentials needed in SP_BYOK_PROVIDER_CONFIG.
# 1. Create an IAM role with KMS permissions.
# 2. Annotate the K8s service account: 
#    kubectl annotate serviceaccount gateway \
#      eks.amazonaws.com/role-arn=arn:aws:iam::ACCOUNT_ID:role/signalpilot-kms-role
# 3. Set SP_BYOK_PROVIDER=aws_kms
# 4. Leave SP_BYOK_PROVIDER_CONFIG unset (boto3 uses instance metadata automatically)
```

2. **Warn at startup** if `aws_access_key_id` appears in `SP_BYOK_PROVIDER_CONFIG`:

```python
# main.py:
if byok_provider_config and "aws_access_key_id" in byok_provider_config:
    if is_cloud_mode():
        logger.warning(
            "SECURITY: SP_BYOK_PROVIDER_CONFIG contains 'aws_access_key_id'. "
            "Consider using IRSA (IAM Roles for Service Accounts) instead of "
            "static credentials. See docs/deployment/byok-aws.md"
        )
```

3. **Optionally: refuse static credentials in cloud mode** and require IRSA:

```python
if is_cloud_mode() and byok_provider_config and "aws_access_key_id" in byok_provider_config:
    raise SystemExit(
        "Static AWS credentials are not allowed in cloud mode. "
        "Configure IRSA for the gateway service account."
    )
```

4. **Support loading credentials from AWS Secrets Manager** instead of env var:

```python
# Alternative: reference secrets by ARN
# SP_BYOK_PROVIDER_CONFIG={"secret_arn": "arn:aws:secretsmanager:us-east-1:123:secret:byok-config"}
```

---

## Verification / test plan

**Unit tests:**
1. `test_static_credentials_warning_in_cloud` — mock `is_cloud_mode=True` and `aws_access_key_id` in config, assert warning logged.
2. `test_irsa_no_credentials_needed` — no credentials in config, AWS SDK uses instance metadata, assert no warning.

**Manual checklist:**
- Set `SP_BYOK_PROVIDER_CONFIG={"aws_access_key_id":"test"}` in cloud mode.
- Verify warning appears in startup logs.
- Verify `/proc/self/environ` exposure risk is documented.

---

## Rollout / migration notes

- Existing deployments with static credentials continue to work (warning only, not hard failure, in the first phase).
- Provide a migration guide from static credentials to IRSA.
- Rollback: remove the warning (credentials still work).
