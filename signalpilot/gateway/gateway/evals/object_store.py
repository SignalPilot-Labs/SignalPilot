"""Store evaluation evidence in S3-compatible object storage.

The store contains transcripts, setup logs, table captures, and export archives.
PostgreSQL and gateway-local disks do not store these objects.

Key layout (org slug first so retention can delete by prefix):

    evals/<org>/runs/<run_id>/transcripts/<task_id>.log
    evals/<org>/runs/<run_id>/setup/<task_id>-<phase>.log
    evals/<org>/runs/<run_id>/artifacts/<task_id>/<file>
    evals/<org>/runs/<run_id>/project.tgz          (private-repo tarball ship)

boto3 is synchronous. run_in_threadpool wraps each boto3 call.
"""

from __future__ import annotations

import logging
import re
from typing import Any

from starlette.concurrency import run_in_threadpool

from gateway.config.evals import EvalRunSettings, get_eval_run_settings

logger = logging.getLogger(__name__)

_SAFE_SEG = re.compile(r"[^a-zA-Z0-9_.-]")


def _seg(value: str) -> str:
    """One path segment: never empty, never traversing, bounded."""
    out = _SAFE_SEG.sub("_", str(value))[:120].strip("._")
    return out or "x"


class EvidenceStoreDisabled(RuntimeError):
    """Report that SP_EVAL_S3_BUCKET is not configured."""


class EvalObjectStore:
    def __init__(self, settings: EvalRunSettings | None = None) -> None:
        self._settings = settings or get_eval_run_settings()
        if not self._settings.s3_bucket:
            raise EvidenceStoreDisabled(
                "SP_EVAL_S3_BUCKET is not set — eval runs need an evidence bucket"
            )
        self.bucket = self._settings.s3_bucket

    # Do not share boto3 clients across thread-pool calls because they are not thread-safe.
    # Create one client for each call.
    def _client(self, *, endpoint_url: str | None = None):
        import boto3
        from botocore.config import Config

        cfg = self._settings
        kwargs: dict[str, Any] = {
            "config": Config(s3={"addressing_style": "path"}, signature_version="s3v4"),
            "region_name": cfg.s3_region or "us-east-1",
        }
        endpoint = endpoint_url if endpoint_url is not None else cfg.s3_endpoint
        if endpoint:
            kwargs["endpoint_url"] = endpoint
        if cfg.s3_access_key:
            kwargs["aws_access_key_id"] = cfg.s3_access_key
            kwargs["aws_secret_access_key"] = cfg.s3_secret_key
        return boto3.client("s3", **kwargs)

    # keys.

    @staticmethod
    def org_prefix(org_id: str) -> str:
        return f"evals/{_seg(org_id)}"

    @classmethod
    def run_prefix(cls, org_id: str, run_id: str) -> str:
        return f"{cls.org_prefix(org_id)}/runs/{_seg(run_id)}"

    @classmethod
    def transcript_key(cls, org_id: str, run_id: str, task_id: str) -> str:
        return f"{cls.run_prefix(org_id, run_id)}/transcripts/{_seg(task_id)}.log"

    @classmethod
    def setup_log_key(cls, org_id: str, run_id: str, task_id: str, phase: str) -> str:
        return f"{cls.run_prefix(org_id, run_id)}/setup/{_seg(task_id)}-{_seg(phase)}.log"

    @classmethod
    def artifact_key(cls, org_id: str, run_id: str, task_id: str, filename: str) -> str:
        return f"{cls.run_prefix(org_id, run_id)}/artifacts/{_seg(task_id)}/{_seg(filename)}"

    @classmethod
    def artifacts_prefix(cls, org_id: str, run_id: str) -> str:
        return f"{cls.run_prefix(org_id, run_id)}/artifacts/"

    @classmethod
    def project_tarball_key(cls, org_id: str, run_id: str) -> str:
        return f"{cls.run_prefix(org_id, run_id)}/project.tgz"

    # ops (async facade).

    async def put_text(self, key: str, text: str) -> int:
        data = text.encode("utf-8", errors="replace")
        await run_in_threadpool(self._put_bytes_sync, key, data, "text/plain; charset=utf-8")
        return len(data)

    async def put_bytes(self, key: str, data: bytes, content_type: str = "application/octet-stream") -> int:
        await run_in_threadpool(self._put_bytes_sync, key, data, content_type)
        return len(data)

    def _put_bytes_sync(self, key: str, data: bytes, content_type: str) -> None:
        self._client().put_object(Bucket=self.bucket, Key=key, Body=data, ContentType=content_type)

    async def get_text(self, key: str) -> str | None:
        data = await run_in_threadpool(self._get_bytes_sync, key)
        return None if data is None else data.decode("utf-8", errors="replace")

    async def get_bytes(self, key: str) -> bytes | None:
        return await run_in_threadpool(self._get_bytes_sync, key)

    def _get_bytes_sync(self, key: str) -> bytes | None:
        try:
            resp = self._client().get_object(Bucket=self.bucket, Key=key)
            return resp["Body"].read()
        except Exception as exc:  # NoSuchKey and friends
            if _is_missing(exc):
                return None
            raise

    async def upload_file(self, key: str, path: str, content_type: str = "application/octet-stream") -> None:
        def _up() -> None:
            self._client().upload_file(
                path, self.bucket, key, ExtraArgs={"ContentType": content_type}
            )

        await run_in_threadpool(_up)

    async def list_keys(self, prefix: str) -> list[dict[str, Any]]:
        def _list() -> list[dict[str, Any]]:
            client = self._client()
            out: list[dict[str, Any]] = []
            token: str | None = None
            while True:
                kwargs: dict[str, Any] = {"Bucket": self.bucket, "Prefix": prefix, "MaxKeys": 1000}
                if token:
                    kwargs["ContinuationToken"] = token
                resp = client.list_objects_v2(**kwargs)
                out.extend(
                    {"key": o["Key"], "size": o["Size"]} for o in resp.get("Contents", [])
                )
                if not resp.get("IsTruncated"):
                    return out
                token = resp.get("NextContinuationToken")

        return await run_in_threadpool(_list)

    async def delete_prefix(self, prefix: str) -> int:
        """Delete every object under prefix; returns count deleted."""
        objs = await self.list_keys(prefix)
        if not objs:
            return 0

        def _delete() -> None:
            client = self._client()
            for i in range(0, len(objs), 1000):
                batch = [{"Key": o["key"]} for o in objs[i : i + 1000]]
                client.delete_objects(Bucket=self.bucket, Delete={"Objects": batch, "Quiet": True})

        await run_in_threadpool(_delete)
        return len(objs)

    async def presign_get(self, key: str, expires_s: int = 3600) -> str:
        def _sign() -> str:
            endpoint = self._settings.s3_runner_endpoint or self._settings.s3_endpoint
            return self._client(endpoint_url=endpoint).generate_presigned_url(
                "get_object",
                Params={"Bucket": self.bucket, "Key": key},
                ExpiresIn=expires_s,
            )

        return await run_in_threadpool(_sign)


def _is_missing(exc: Exception) -> bool:
    code = ""
    resp = getattr(exc, "response", None)
    if isinstance(resp, dict):
        code = str(resp.get("Error", {}).get("Code", ""))
    return code in {"NoSuchKey", "404", "NotFound"}


def get_object_store() -> EvalObjectStore:
    """Return a new facade that uses cached settings."""
    return EvalObjectStore()
