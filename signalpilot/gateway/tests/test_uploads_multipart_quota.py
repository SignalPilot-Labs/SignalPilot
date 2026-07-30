"""Tests for the eval multipart upload session: part-length binding, owner
binding, and per-principal quota.

The gateway never sees the bytes, so everything here is about what the server
commits to before handing out presigned URLs.
"""

from __future__ import annotations

import time

import pytest
from fastapi import HTTPException

from gateway.api import uploads
from gateway.config.uploads import EvalUploadsSettings

PART = uploads.PART_SIZE


@pytest.fixture(autouse=True)
def _clean_sessions():
    uploads._sessions.clear()
    yield
    uploads._sessions.clear()


def _cfg(max_mb: int = 8192) -> EvalUploadsSettings:
    return EvalUploadsSettings(
        SP_EVAL_UPLOADS_BUCKET="evals",
        SP_EVAL_UPLOADS_MAX_MB=max_mb,
        SP_EVAL_UPLOADS_S3_ACCESS_KEY="AK",
        SP_EVAL_UPLOADS_S3_SECRET_KEY="SK",
        SP_EVAL_UPLOADS_S3_REGION="us-east-1",
    )


class _FakeS3:
    """Records generate_presigned_url params so the signed plan is inspectable."""

    def __init__(self):
        self.presign_params: list[dict] = []
        self.deleted: list[str] = []
        self.head_size = 0
        self.aborted: list[str] = []

    def create_multipart_upload(self, **kwargs):
        return {"UploadId": "upload-1"}

    def generate_presigned_url(self, op, Params, ExpiresIn):
        self.presign_params.append({**Params, "_expires_in": ExpiresIn})
        return f"https://s3.test/{Params['Key']}?partNumber={Params['PartNumber']}"

    def complete_multipart_upload(self, **kwargs):
        return {}

    def head_object(self, **kwargs):
        return {"ContentLength": self.head_size}

    def delete_object(self, Bucket, Key):
        self.deleted.append(Key)

    def abort_multipart_upload(self, **kwargs):
        self.aborted.append(kwargs.get("Key", ""))


@pytest.fixture
def fake_s3(monkeypatch):
    s3 = _FakeS3()
    monkeypatch.setattr(uploads, "_s3_client", lambda cfg, presign=False: s3)
    monkeypatch.setattr(uploads, "get_eval_uploads_settings", _cfg)
    monkeypatch.setattr(uploads, "_notify", lambda *a, **k: None)
    return s3


# ─── Part-length binding ─────────────────────────────────────────────────────


class TestPartLengthBinding:
    def test_part_plan_covers_exact_declared_size(self):
        assert uploads._part_plan(PART + 10) == [PART, 10]
        assert uploads._part_plan(PART) == [PART]
        assert uploads._part_plan(1) == [1]
        assert sum(uploads._part_plan(3 * PART + 77)) == 3 * PART + 77

    @pytest.mark.asyncio
    async def test_each_presigned_part_binds_its_content_length(self, fake_s3):
        req = uploads.InitiateRequest(filename="a.zip", size_bytes=PART + 500)
        await uploads.initiate_eval_upload("user-1", req)

        lengths = [p["ContentLength"] for p in fake_s3.presign_params]
        assert lengths == [PART, 500]

    @pytest.mark.asyncio
    async def test_presign_expiry_is_short(self, fake_s3):
        req = uploads.InitiateRequest(filename="a.zip", size_bytes=10)
        await uploads.initiate_eval_upload("user-1", req)
        assert fake_s3.presign_params[0]["_expires_in"] <= 3600

    def test_boto3_signs_content_length_header(self):
        """ContentLength must land in X-Amz-SignedHeaders or the binding is a no-op."""
        import boto3
        from botocore.config import Config

        client = boto3.client(
            "s3",
            aws_access_key_id="AK",
            aws_secret_access_key="SK",
            region_name="us-east-1",
            config=Config(s3={"addressing_style": "path"}, signature_version="s3v4"),
        )
        url = client.generate_presigned_url(
            "upload_part",
            Params={"Bucket": "b", "Key": "k", "UploadId": "u", "PartNumber": 1, "ContentLength": 1234},
            ExpiresIn=600,
        )
        assert "content-length" in url.lower()


# ─── Owner binding + quota ───────────────────────────────────────────────────


class TestUploadSessionOwnership:
    @pytest.mark.asyncio
    async def test_initiate_registers_owner_bound_session(self, fake_s3):
        req = uploads.InitiateRequest(filename="a.zip", size_bytes=PART + 1)
        resp = await uploads.initiate_eval_upload("user-1", req)
        session = uploads._sessions[resp.key]
        assert session.user_id == "user-1"
        assert session.size_bytes == PART + 1
        assert session.expires_at > time.monotonic()

    @pytest.mark.asyncio
    async def test_complete_by_other_principal_rejected(self, fake_s3):
        resp = await uploads.initiate_eval_upload(
            "user-1", uploads.InitiateRequest(filename="a.zip", size_bytes=10)
        )
        with pytest.raises(HTTPException) as exc:
            await uploads.complete_eval_upload(
                "user-2",
                uploads.CompleteRequest(
                    key=resp.key,
                    upload_id=resp.upload_id,
                    parts=[uploads.CompletedPart(part_number=1, etag="e")],
                ),
            )
        assert exc.value.status_code == 404

    @pytest.mark.asyncio
    async def test_complete_without_session_rejected(self, fake_s3):
        """A key/upload_id pair the gateway never issued cannot be completed."""
        with pytest.raises(HTTPException) as exc:
            await uploads.complete_eval_upload(
                "user-1",
                uploads.CompleteRequest(
                    key="uploads/2026-01-01/aabbccdd/x.zip",
                    upload_id="forged",
                    parts=[uploads.CompletedPart(part_number=1, etag="e")],
                ),
            )
        assert exc.value.status_code == 404

    @pytest.mark.asyncio
    async def test_complete_rejects_parts_beyond_the_plan(self, fake_s3):
        resp = await uploads.initiate_eval_upload(
            "user-1", uploads.InitiateRequest(filename="a.zip", size_bytes=10)
        )
        with pytest.raises(HTTPException) as exc:
            await uploads.complete_eval_upload(
                "user-1",
                uploads.CompleteRequest(
                    key=resp.key,
                    upload_id=resp.upload_id,
                    parts=[
                        uploads.CompletedPart(part_number=1, etag="e"),
                        uploads.CompletedPart(part_number=2, etag="e"),
                    ],
                ),
            )
        assert exc.value.status_code == 400

    @pytest.mark.asyncio
    async def test_oversized_object_deleted_against_declared_size(self, fake_s3):
        resp = await uploads.initiate_eval_upload(
            "user-1", uploads.InitiateRequest(filename="a.zip", size_bytes=1024)
        )
        fake_s3.head_size = 500 * 1024 * 1024  # far above the claim, under max_bytes
        with pytest.raises(HTTPException) as exc:
            await uploads.complete_eval_upload(
                "user-1",
                uploads.CompleteRequest(
                    key=resp.key,
                    upload_id=resp.upload_id,
                    parts=[uploads.CompletedPart(part_number=1, etag="e")],
                ),
            )
        assert exc.value.status_code == 413
        assert resp.key in fake_s3.deleted

    @pytest.mark.asyncio
    async def test_abort_requires_the_owning_principal(self, fake_s3):
        resp = await uploads.initiate_eval_upload(
            "user-1", uploads.InitiateRequest(filename="a.zip", size_bytes=10)
        )
        with pytest.raises(HTTPException) as exc:
            await uploads.abort_eval_upload(
                "user-2", uploads.AbortRequest(key=resp.key, upload_id=resp.upload_id)
            )
        assert exc.value.status_code == 404
        assert fake_s3.aborted == []

        await uploads.abort_eval_upload(
            "user-1", uploads.AbortRequest(key=resp.key, upload_id=resp.upload_id)
        )
        assert fake_s3.aborted == [resp.key]
        assert resp.key not in uploads._sessions


class TestPerPrincipalQuota:
    @pytest.mark.asyncio
    async def test_open_upload_count_capped(self, fake_s3):
        for _ in range(uploads._MAX_OPEN_UPLOADS_PER_USER):
            await uploads.initiate_eval_upload(
                "user-1", uploads.InitiateRequest(filename="a.zip", size_bytes=10)
            )
        with pytest.raises(HTTPException) as exc:
            await uploads.initiate_eval_upload(
                "user-1", uploads.InitiateRequest(filename="a.zip", size_bytes=10)
            )
        assert exc.value.status_code == 429

    @pytest.mark.asyncio
    async def test_concurrent_bytes_capped(self, monkeypatch, fake_s3):
        small = lambda: _cfg(max_mb=128)  # noqa: E731
        monkeypatch.setattr(uploads, "get_eval_uploads_settings", small)
        await uploads.initiate_eval_upload(
            "user-1", uploads.InitiateRequest(filename="a.zip", size_bytes=100 * 1024 * 1024)
        )
        with pytest.raises(HTTPException) as exc:
            await uploads.initiate_eval_upload(
                "user-1", uploads.InitiateRequest(filename="b.zip", size_bytes=100 * 1024 * 1024)
            )
        assert exc.value.status_code == 429

    @pytest.mark.asyncio
    async def test_quota_is_per_principal(self, monkeypatch, fake_s3):
        for _ in range(uploads._MAX_OPEN_UPLOADS_PER_USER):
            await uploads.initiate_eval_upload(
                "user-1", uploads.InitiateRequest(filename="a.zip", size_bytes=10)
            )
        resp = await uploads.initiate_eval_upload(
            "user-2", uploads.InitiateRequest(filename="a.zip", size_bytes=10)
        )
        assert uploads._sessions[resp.key].user_id == "user-2"

    def test_expired_sessions_stop_counting(self):
        uploads._sessions["k"] = uploads._UploadSession(
            key="k", upload_id="u", user_id="user-1", size_bytes=1, expires_at=time.monotonic() - 1
        )
        uploads._check_quota("user-1", 1, 1024)
        assert "k" not in uploads._sessions
