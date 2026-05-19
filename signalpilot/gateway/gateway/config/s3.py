"""S3 storage settings for the gateway.

Class A vars managed here: SP_S3_ENDPOINT_URL, SP_S3_ACCESS_KEY,
SP_S3_SECRET_KEY, SP_S3_BUCKET, SP_S3_REGION
"""

from __future__ import annotations

from functools import lru_cache

from pydantic import Field

from ._base import _GatewaySettingsBase


class S3Settings(_GatewaySettingsBase):
    sp_s3_endpoint_url: str | None = Field(None, alias="SP_S3_ENDPOINT_URL")
    sp_s3_access_key: str | None = Field(None, alias="SP_S3_ACCESS_KEY")
    sp_s3_secret_key: str | None = Field(None, alias="SP_S3_SECRET_KEY")
    sp_s3_bucket: str = Field("signalpilot-data", alias="SP_S3_BUCKET")
    sp_s3_region: str = Field("us-east-1", alias="SP_S3_REGION")

    @property
    def enabled(self) -> bool:
        return bool(self.sp_s3_bucket)


@lru_cache(maxsize=1)
def get_s3_settings() -> S3Settings:
    return S3Settings()
