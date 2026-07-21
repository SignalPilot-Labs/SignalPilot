"""Eval upload endpoints — presigned S3 multipart upload, notify the team.

Deliberately minimal (see eval-upload-spec.md at repo root): no database rows,
no download path, no processing. S3 is the record; a bucket lifecycle rule
handles the 7-day deletion (and aborts stale multipart uploads); the
notification is one email.

Flow (industry-standard direct-to-S3 multipart):
  1. POST /api/evals/upload/initiate  — validate name/size, CreateMultipartUpload,
     return presigned per-part PUT URLs. The browser uploads parts straight to
     S3 in parallel; the gateway never touches file bytes.
  2. POST /api/evals/upload/complete  — CompleteMultipartUpload, verify final
     size, email the team.
  3. POST /api/evals/upload/abort     — best-effort cleanup on client failure.

A legacy single-POST endpoint remains for small files / older clients.
"""

from __future__ import annotations

import logging
import math
import re
import secrets
import smtplib
from datetime import UTC, datetime, timedelta
from email.message import EmailMessage

from fastapi import APIRouter, Form, HTTPException, UploadFile
from pydantic import BaseModel, Field
from starlette.concurrency import run_in_threadpool

from ..auth import UserID
from ..config.uploads import EvalUploadsSettings, get_eval_uploads_settings
from ..security.scope_guard import RequireScope

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api")

_FILENAME_SAFE = re.compile(r"[^a-zA-Z0-9._-]")
# Keys are generated server-side; complete/abort re-validate shape so a caller
# can't point these endpoints at arbitrary bucket keys.
_KEY_PATTERN = re.compile(r"^uploads/\d{4}-\d{2}-\d{2}/[0-9a-f]{8}/[A-Za-z0-9._-]+\.zip$")

PART_SIZE = 64 * 1024 * 1024  # 64 MB parts → 8 GB ≈ 128 parts (S3 max 10k)
_PRESIGN_EXPIRY_S = 12 * 3600  # generous window for slow links on large files


def _sanitize_filename(name: str) -> str:
    base = (name or "upload.zip").rsplit("/", 1)[-1].rsplit("\\", 1)[-1]
    return _FILENAME_SAFE.sub("_", base)[-128:]


def _s3_client(cfg: EvalUploadsSettings, *, presign: bool = False):
    """Build the S3 client; presign=True uses the browser-reachable endpoint.

    Locally the gateway reaches MinIO at http://minio:9000 (compose DNS) but
    the browser must hit http://localhost:9000 — presigned URLs embed the host
    in the signature, so they are signed against the public endpoint.
    """
    import boto3
    from botocore.config import Config

    # SigV4 explicitly: presigned URLs default to legacy SigV2 with custom
    # endpoints, and real S3 rejects V2 in modern regions.
    kwargs: dict = {
        "config": Config(s3={"addressing_style": "path"}, signature_version="s3v4")
    }
    endpoint = cfg.s3_public_endpoint if presign and cfg.s3_public_endpoint else cfg.s3_endpoint
    if endpoint:
        kwargs["endpoint_url"] = endpoint
    if cfg.s3_region:
        kwargs["region_name"] = cfg.s3_region
    if cfg.s3_access_key and cfg.s3_secret_key:
        kwargs["aws_access_key_id"] = cfg.s3_access_key
        kwargs["aws_secret_access_key"] = cfg.s3_secret_key
        kwargs.setdefault("region_name", "us-east-1")
    return boto3.client("s3", **kwargs)


def _notify(cfg: EvalUploadsSettings, *, user_id: str, filename: str, size_mb: float,
            notes: str, key: str, expires: str) -> None:
    """Send the team notification. Plain text on purpose — notes is user input."""
    if not cfg.notify_email:
        return
    body = (
        f"New eval upload from user {user_id}\n"
        f"File: {filename} ({size_mb:.1f} MB)\n"
        f"Notes: {notes or '(none)'}\n"
        f"Retrieve: aws s3 cp s3://{cfg.bucket}/{key} .\n"
        f"Auto-deletes: {expires}\n"
    )
    subject = f"New eval upload: {filename}"
    if cfg.smtp_host:
        msg = EmailMessage()
        msg["From"] = cfg.notify_from
        msg["To"] = cfg.notify_email
        msg["Subject"] = subject
        msg.set_content(body)
        with smtplib.SMTP(cfg.smtp_host, cfg.smtp_port, timeout=10) as smtp:
            smtp.send_message(msg)
    else:
        import boto3

        boto3.client("ses").send_email(
            Source=cfg.notify_from,
            Destination={"ToAddresses": [cfg.notify_email]},
            Message={
                "Subject": {"Data": subject},
                "Body": {"Text": {"Data": body}},
            },
        )


def _require_enabled() -> EvalUploadsSettings:
    cfg = get_eval_uploads_settings()
    if not cfg.enabled:
        raise HTTPException(status_code=404, detail="Eval uploads are not enabled")
    return cfg


def _new_key(filename: str) -> tuple[str, str, str]:
    """Return (key, reference_id, expires) for a fresh upload."""
    now = datetime.now(UTC)
    short_id = secrets.token_hex(4)
    key = f"uploads/{now:%Y-%m-%d}/{short_id}/{filename}"
    reference_id = f"eval-{now:%Y%m%d}-{short_id}"
    expires = f"{now + timedelta(days=7):%Y-%m-%d}"
    return key, reference_id, expires


def _reference_from_key(key: str) -> str:
    _, date_part, short_id, _ = key.split("/", 3)
    return f"eval-{date_part.replace('-', '')}-{short_id}"


# ---------------------------------------------------------------------------
# Multipart flow
# ---------------------------------------------------------------------------


class InitiateRequest(BaseModel):
    filename: str = Field(min_length=1, max_length=512)
    size_bytes: int = Field(gt=0)
    notes: str = Field("", max_length=2000)


class InitiateResponse(BaseModel):
    key: str
    upload_id: str
    reference_id: str
    part_size: int
    part_urls: list[str]


class CompletedPart(BaseModel):
    part_number: int = Field(ge=1, le=10_000)
    etag: str = Field(min_length=1, max_length=256)


class CompleteRequest(BaseModel):
    key: str
    upload_id: str
    parts: list[CompletedPart] = Field(min_length=1, max_length=10_000)
    notes: str = Field("", max_length=2000)


class AbortRequest(BaseModel):
    key: str
    upload_id: str


def _validate_key(key: str) -> None:
    if not _KEY_PATTERN.match(key):
        raise HTTPException(status_code=400, detail="Invalid upload key")


@router.post("/evals/upload/initiate", dependencies=[RequireScope("write")])
async def initiate_eval_upload(user_id: UserID, req: InitiateRequest) -> InitiateResponse:
    """Start a multipart upload and presign one PUT URL per part."""
    cfg = _require_enabled()

    filename = _sanitize_filename(req.filename)
    if not filename.lower().endswith(".zip"):
        raise HTTPException(status_code=415, detail="Only .zip files are accepted")
    if req.size_bytes > cfg.max_bytes:
        raise HTTPException(
            status_code=413,
            detail=f"File is {req.size_bytes // (1024 * 1024)} MB — the limit is {cfg.max_mb} MB",
        )

    key, reference_id, _ = _new_key(filename)
    part_count = max(1, math.ceil(req.size_bytes / PART_SIZE))

    def _initiate() -> InitiateResponse:
        client = _s3_client(cfg)
        mpu = client.create_multipart_upload(
            Bucket=cfg.bucket,
            Key=key,
            Metadata={
                "uploader-user-id": user_id,
                # S3 metadata must be ASCII — notes travel in full via the email.
                "notes": req.notes.encode("ascii", "replace").decode()[:512],
            },
        )
        upload_id = mpu["UploadId"]
        signer = _s3_client(cfg, presign=True)
        part_urls = [
            signer.generate_presigned_url(
                "upload_part",
                Params={
                    "Bucket": cfg.bucket,
                    "Key": key,
                    "UploadId": upload_id,
                    "PartNumber": n,
                },
                ExpiresIn=_PRESIGN_EXPIRY_S,
            )
            for n in range(1, part_count + 1)
        ]
        return InitiateResponse(
            key=key,
            upload_id=upload_id,
            reference_id=reference_id,
            part_size=PART_SIZE,
            part_urls=part_urls,
        )

    return await run_in_threadpool(_initiate)


@router.post("/evals/upload/complete", dependencies=[RequireScope("write")])
async def complete_eval_upload(user_id: UserID, req: CompleteRequest):
    """Finish the multipart upload, verify size, and email the team."""
    cfg = _require_enabled()
    _validate_key(req.key)

    def _complete() -> int:
        client = _s3_client(cfg)
        client.complete_multipart_upload(
            Bucket=cfg.bucket,
            Key=req.key,
            UploadId=req.upload_id,
            MultipartUpload={
                "Parts": [
                    {"PartNumber": p.part_number, "ETag": p.etag}
                    for p in sorted(req.parts, key=lambda p: p.part_number)
                ]
            },
        )
        size = client.head_object(Bucket=cfg.bucket, Key=req.key)["ContentLength"]
        if size > cfg.max_bytes:
            # Presigned parts don't bind Content-Length; enforce the cap here.
            client.delete_object(Bucket=cfg.bucket, Key=req.key)
            raise HTTPException(
                status_code=413,
                detail=f"Upload is {size // (1024 * 1024)} MB — the limit is {cfg.max_mb} MB",
            )
        return size

    size = await run_in_threadpool(_complete)

    reference_id = _reference_from_key(req.key)
    expires = f"{datetime.now(UTC) + timedelta(days=7):%Y-%m-%d}"
    notes = req.notes[:2000]

    try:
        await run_in_threadpool(
            _notify,
            cfg,
            user_id=user_id,
            filename=req.key.rsplit("/", 1)[-1],
            size_mb=size / (1024 * 1024),
            notes=notes,
            key=req.key,
            expires=expires,
        )
    except Exception:
        # The upload is the thing that matters; a lost email is recoverable
        # from the S3 listing.
        logger.exception("Eval upload notification failed (upload succeeded: %s)", req.key)

    return {"reference_id": reference_id, "expires_at": expires}


@router.post("/evals/upload/abort", status_code=204, dependencies=[RequireScope("write")])
async def abort_eval_upload(req: AbortRequest) -> None:
    """Best-effort cleanup when the client gives up; lifecycle rules are the backstop."""
    cfg = _require_enabled()
    _validate_key(req.key)

    def _abort() -> None:
        client = _s3_client(cfg)
        try:
            client.abort_multipart_upload(
                Bucket=cfg.bucket, Key=req.key, UploadId=req.upload_id
            )
        except Exception:
            logger.warning("Abort failed for %s (lifecycle rule will clean up)", req.key)

    await run_in_threadpool(_abort)


# ---------------------------------------------------------------------------
# Legacy single-POST flow (small files / older clients)
# ---------------------------------------------------------------------------


@router.post("/evals/upload", status_code=201, dependencies=[RequireScope("write")])
async def upload_eval(user_id: UserID, file: UploadFile, notes: str = Form("")):
    """Store an uploaded eval .zip in S3 and email the team."""
    cfg = _require_enabled()

    filename = _sanitize_filename(file.filename or "")
    if not filename.lower().endswith(".zip"):
        raise HTTPException(status_code=415, detail="Only .zip files are accepted")

    # FastAPI has already spooled the body; measure and sniff from the spool.
    file.file.seek(0, 2)
    size = file.file.tell()
    file.file.seek(0)
    if size > cfg.max_bytes:
        raise HTTPException(
            status_code=413,
            detail=f"File is {size // (1024 * 1024)} MB — the limit is {cfg.max_mb} MB",
        )
    if file.file.read(2) != b"PK":
        raise HTTPException(status_code=415, detail="File is not a valid zip archive")
    file.file.seek(0)

    key, reference_id, expires = _new_key(filename)
    notes = notes[:2000]

    client = _s3_client(cfg)
    await run_in_threadpool(
        client.upload_fileobj,
        file.file,
        cfg.bucket,
        key,
        ExtraArgs={
            "Metadata": {
                "uploader-user-id": user_id,
                "notes": notes.encode("ascii", "replace").decode()[:512],
            }
        },
    )

    try:
        await run_in_threadpool(
            _notify,
            cfg,
            user_id=user_id,
            filename=filename,
            size_mb=size / (1024 * 1024),
            notes=notes,
            key=key,
            expires=expires,
        )
    except Exception:
        logger.exception("Eval upload notification failed (upload succeeded: %s)", key)

    return {"reference_id": reference_id, "expires_at": expires}
