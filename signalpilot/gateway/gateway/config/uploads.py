"""Eval-upload settings for the gateway.

Cached because no test monkeypatches these vars after import (new vars,
verified by grep at introduction — audit tests/ before adding more).

Class A vars managed here:
    SP_EVAL_UPLOADS_BUCKET          — S3 bucket name; feature disabled when unset
    SP_EVAL_UPLOADS_NOTIFY_EMAIL    — team address that receives upload notifications
    SP_EVAL_UPLOADS_NOTIFY_FROM     — From: address for notifications
    SP_EVAL_UPLOADS_MAX_MB          — upload size cap in MB
    SP_EVAL_UPLOADS_S3_ENDPOINT     — S3 endpoint override (MinIO in local testing)
    SP_EVAL_UPLOADS_SMTP_HOST/PORT  — when set, notify via plain SMTP instead of SES
                                      (local testing with Mailpit; production uses SES)
"""

from __future__ import annotations

from functools import lru_cache

from pydantic import Field

from ._base import _GatewaySettingsBase


class EvalUploadsSettings(_GatewaySettingsBase):
    """Typed eval-upload configuration read from process environment at instantiation."""

    bucket: str = Field("", alias="SP_EVAL_UPLOADS_BUCKET")
    notify_email: str = Field("", alias="SP_EVAL_UPLOADS_NOTIFY_EMAIL")
    notify_from: str = Field("eval-uploads@signalpilot.dev", alias="SP_EVAL_UPLOADS_NOTIFY_FROM")
    max_mb: int = Field(500, alias="SP_EVAL_UPLOADS_MAX_MB")
    s3_endpoint: str = Field("", alias="SP_EVAL_UPLOADS_S3_ENDPOINT")
    # Explicit credentials for the upload bucket only (MinIO locally). When
    # empty, boto3's default chain applies (IAM role in cloud) — kept separate
    # from global AWS_* env so local MinIO creds can't leak into BYOK/Redshift.
    s3_access_key: str = Field("", alias="SP_EVAL_UPLOADS_S3_ACCESS_KEY")
    s3_secret_key: str = Field("", alias="SP_EVAL_UPLOADS_S3_SECRET_KEY")
    smtp_host: str = Field("", alias="SP_EVAL_UPLOADS_SMTP_HOST")
    smtp_port: int = Field(1025, alias="SP_EVAL_UPLOADS_SMTP_PORT")

    @property
    def enabled(self) -> bool:
        return bool(self.bucket)

    @property
    def max_bytes(self) -> int:
        return self.max_mb * 1024 * 1024


@lru_cache(maxsize=1)
def get_eval_uploads_settings() -> EvalUploadsSettings:
    """Return cached EvalUploadsSettings instance."""
    return EvalUploadsSettings()
