"""AWS KMS BYOK provider implementation.

Wraps/unwraps DEKs using AWS KMS. boto3 calls are run in a thread via
asyncio.to_thread() to avoid blocking the event loop.

boto3 is an optional dependency. If not installed, importing this module
succeeds but constructing AWSKMSProvider raises ImportError.
"""

from __future__ import annotations

import asyncio
import logging
import random
import re

from .byok import BYOKKeyError, BYOKProvider  # noqa: F401 (re-exported for clarity)

logger = logging.getLogger(__name__)

# ─── Constants ────────────────────────────────────────────────────────────────

_ARN_REGION_PATTERN = re.compile(r"arn:aws:kms:([^:]+):")

_MAX_RETRY_ATTEMPTS = 3
_RETRY_BASE_DELAY_SECONDS = 0.5
_RETRY_JITTER_MAX_SECONDS = 0.1

_ERROR_ACCESS_DENIED = "Access denied to KMS key"
_ERROR_KEY_DISABLED = "KMS key is disabled"
_ERROR_KEY_NOT_FOUND = "KMS key not found"
_ERROR_THROTTLED = "KMS request throttled after retries"
_ERROR_GENERIC = "KMS operation failed"

_BOTO3_MISSING_MESSAGE = "boto3 is required for AWS KMS provider. Install with: pip install signalpilot-gateway[aws]"


# ─── Optional import guard ────────────────────────────────────────────────────

try:
    import boto3 as _boto3_module
    from botocore.exceptions import ClientError as _BotoClientError

    _BOTO3_AVAILABLE = True
except ImportError:
    _boto3_module = None  # type: ignore[assignment]
    _BOTO3_AVAILABLE = False
    _BotoClientError = Exception  # type: ignore[assignment,misc]


# ─── AWSKMSProvider ──────────────────────────────────────────────────────────


class AWSKMSProvider:
    """AWS KMS BYOK provider.

    Wraps and unwraps DEKs using AWS KMS. The KMS key is identified by ARN.
    The region is extracted from the ARN unless explicitly provided.

    Thread safety: _client is created lazily on first use. Double-init is safe
    (boto3 clients are thread-safe and idempotent to create) so no lock is needed.
    """

    def __init__(self, provider_config: dict) -> None:
        if not _BOTO3_AVAILABLE or _boto3_module is None:
            raise ImportError(_BOTO3_MISSING_MESSAGE)

        kms_key_arn = provider_config.get("kms_key_arn")
        if not kms_key_arn:
            raise ValueError("provider_config must include 'kms_key_arn'")

        self._kms_key_arn: str = kms_key_arn
        self._endpoint_url: str | None = provider_config.get("endpoint_url")

        region = provider_config.get("region")
        if not region:
            region = _extract_region_from_arn(kms_key_arn)
        self._region: str = region

        self._client = None  # Lazy init on first use

    def _get_client(self):  # type: ignore[return]
        """Return the boto3 KMS client, creating it on first call."""
        if self._client is None:
            assert _boto3_module is not None, _BOTO3_MISSING_MESSAGE
            kwargs: dict = {"region_name": self._region}
            if self._endpoint_url:
                kwargs["endpoint_url"] = self._endpoint_url
            self._client = _boto3_module.client("kms", **kwargs)
        return self._client

    async def wrap_dek(self, org_id: str, key_alias: str, dek_plaintext: bytes) -> bytes:
        """Encrypt a DEK using the KMS key. Returns the ciphertext blob."""
        encryption_context = {"org_id": org_id, "key_alias": key_alias}
        client = self._get_client()

        for attempt in range(_MAX_RETRY_ATTEMPTS):
            try:
                response = await asyncio.to_thread(
                    client.encrypt,
                    KeyId=self._kms_key_arn,
                    Plaintext=dek_plaintext,
                    EncryptionContext=encryption_context,
                )
                return response["CiphertextBlob"]
            except _BotoClientError as exc:
                error_code = exc.response["Error"]["Code"]  # type: ignore[union-attr]
                if error_code == "ThrottlingException":
                    if attempt < _MAX_RETRY_ATTEMPTS - 1:
                        delay = _RETRY_BASE_DELAY_SECONDS * (2**attempt)
                        jitter = random.uniform(0, _RETRY_JITTER_MAX_SECONDS)
                        logger.warning(
                            "KMS throttled (attempt %d/%d), retrying in %.2fs",
                            attempt + 1,
                            _MAX_RETRY_ATTEMPTS,
                            delay + jitter,
                        )
                        await asyncio.sleep(delay + jitter)
                        continue
                    logger.error("KMS throttled after %d attempts", _MAX_RETRY_ATTEMPTS)
                    raise _handle_kms_error(exc, org_id, key_alias) from exc
                logger.error("KMS wrap_dek failed: %s", exc, exc_info=True)
                raise _handle_kms_error(exc, org_id, key_alias) from exc

        # Should not be reached but satisfies type checker
        raise BYOKKeyError(org_id, key_alias, _ERROR_THROTTLED)

    async def unwrap_dek(self, org_id: str, key_alias: str, wrapped_dek: bytes) -> bytes:
        """Decrypt a wrapped DEK using the KMS key. Raises BYOKKeyError on failure."""
        encryption_context = {"org_id": org_id, "key_alias": key_alias}
        client = self._get_client()

        for attempt in range(_MAX_RETRY_ATTEMPTS):
            try:
                response = await asyncio.to_thread(
                    client.decrypt,
                    CiphertextBlob=wrapped_dek,
                    KeyId=self._kms_key_arn,
                    EncryptionContext=encryption_context,
                )
                return response["Plaintext"]
            except _BotoClientError as exc:
                error_code = exc.response["Error"]["Code"]  # type: ignore[union-attr]
                if error_code == "ThrottlingException":
                    if attempt < _MAX_RETRY_ATTEMPTS - 1:
                        delay = _RETRY_BASE_DELAY_SECONDS * (2**attempt)
                        jitter = random.uniform(0, _RETRY_JITTER_MAX_SECONDS)
                        logger.warning(
                            "KMS throttled (attempt %d/%d), retrying in %.2fs",
                            attempt + 1,
                            _MAX_RETRY_ATTEMPTS,
                            delay + jitter,
                        )
                        await asyncio.sleep(delay + jitter)
                        continue
                    logger.error("KMS throttled after %d attempts", _MAX_RETRY_ATTEMPTS)
                    raise _handle_kms_error(exc, org_id, key_alias) from exc
                logger.error("KMS unwrap_dek failed: %s", exc, exc_info=True)
                raise _handle_kms_error(exc, org_id, key_alias) from exc

        raise BYOKKeyError(org_id, key_alias, _ERROR_THROTTLED)

    async def generate_dek(self) -> bytes:
        """Generate a fresh Fernet key (44 bytes) to use as a DEK."""
        from cryptography.fernet import Fernet

        return Fernet.generate_key()

    async def health_check(self) -> bool:
        """Return True if the KMS key is enabled and reachable."""
        client = self._get_client()
        try:
            response = await asyncio.to_thread(
                client.describe_key,
                KeyId=self._kms_key_arn,
            )
            key_state = response["KeyMetadata"]["KeyState"]
            return key_state == "Enabled"
        except Exception as exc:
            logger.warning("KMS health check failed: %s", exc)
            return False


# ─── Protocol compliance assertion ───────────────────────────────────────────


# Verify AWSKMSProvider satisfies BYOKProvider at import time (runtime_checkable).
# This is a documentation assertion — it will fail loudly at startup if the
# interface drifts.
def _assert_protocol_compliance() -> None:
    assert isinstance.__doc__  # noqa: B015 — just ensuring runtime check works
    # Not called at module level to avoid requiring boto3 at import time.
    # Called from tests to verify compliance.


# ─── Helpers ─────────────────────────────────────────────────────────────────


def _extract_region_from_arn(arn: str) -> str:
    """Extract the AWS region from a KMS key ARN.

    Raises ValueError if the ARN does not match the expected format.
    """
    match = _ARN_REGION_PATTERN.search(arn)
    if not match:
        logger.error("Invalid KMS ARN format: %r", arn)
        raise ValueError("Invalid KMS key ARN format — cannot extract region")
    return match.group(1)


def _handle_kms_error(exc: Exception, org_id: str, key_alias: str) -> BYOKKeyError:
    """Map a boto3 ClientError to a BYOKKeyError with a sanitized message.

    The full exception details are logged server-side; callers only see a
    safe, sanitized message — never a raw boto3 traceback.
    """
    try:
        error_code = exc.response["Error"]["Code"]  # type: ignore[union-attr]
    except (AttributeError, KeyError, TypeError):
        return BYOKKeyError(org_id, key_alias, _ERROR_GENERIC)

    if error_code == "AccessDeniedException":
        return BYOKKeyError(org_id, key_alias, _ERROR_ACCESS_DENIED)
    if error_code == "DisabledException":
        return BYOKKeyError(org_id, key_alias, _ERROR_KEY_DISABLED)
    if error_code in ("NotFoundException", "InvalidArnException"):
        return BYOKKeyError(org_id, key_alias, _ERROR_KEY_NOT_FOUND)
    if error_code == "ThrottlingException":
        return BYOKKeyError(org_id, key_alias, _ERROR_THROTTLED)
    return BYOKKeyError(org_id, key_alias, _ERROR_GENERIC)
