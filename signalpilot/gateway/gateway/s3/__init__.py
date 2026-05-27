"""S3 storage integration for the gateway."""

from __future__ import annotations

import logging
from typing import Any

from .client import S3Client

logger = logging.getLogger(__name__)

_boto_client: Any = None
_bucket: str = ""


def get_raw_s3_client() -> Any | None:
    return _boto_client


def get_s3_bucket() -> str:
    return _bucket


def get_s3(org_id: str) -> S3Client:
    return S3Client(get_raw_s3_client(), _bucket, org_id)


async def init_s3() -> None:
    global _boto_client, _bucket

    from ..config import get_s3_settings

    settings = get_s3_settings()
    if not settings.enabled:
        logger.info("S3 storage disabled (SP_S3_BUCKET not set)")
        return

    import asyncio

    import boto3
    from botocore.config import Config as BotoConfig
    from botocore.exceptions import ClientError

    kwargs: dict = {
        "region_name": settings.sp_s3_region,
        "config": BotoConfig(signature_version="s3v4"),
    }
    if settings.sp_s3_endpoint_url:
        kwargs["endpoint_url"] = settings.sp_s3_endpoint_url
    if settings.sp_s3_access_key and settings.sp_s3_secret_key:
        kwargs["aws_access_key_id"] = settings.sp_s3_access_key
        kwargs["aws_secret_access_key"] = settings.sp_s3_secret_key

    _boto_client = boto3.client("s3", **kwargs)
    _bucket = settings.sp_s3_bucket

    loop = asyncio.get_event_loop()
    try:
        await loop.run_in_executor(None, lambda: _boto_client.head_bucket(Bucket=_bucket))
        logger.info("S3 bucket '%s' exists", _bucket)
    except ClientError as e:
        code = e.response.get("Error", {}).get("Code", "")
        if code in ("404", "NoSuchBucket"):
            try:
                create_args: dict = {"Bucket": _bucket}
                if settings.sp_s3_region != "us-east-1":
                    create_args["CreateBucketConfiguration"] = {"LocationConstraint": settings.sp_s3_region}
                await loop.run_in_executor(None, lambda: _boto_client.create_bucket(**create_args))
                logger.info("S3 bucket '%s' created", _bucket)
            except Exception as create_err:
                logger.warning("S3 bucket creation failed: %s", create_err)
        else:
            logger.warning("S3 bucket check failed: %s", e)
    except Exception as e:
        logger.warning("S3 connection failed (MinIO/S3 may not be running): %s", type(e).__name__)
        _boto_client = None


__all__ = ["S3Client", "get_s3", "get_raw_s3_client", "get_s3_bucket", "init_s3"]
