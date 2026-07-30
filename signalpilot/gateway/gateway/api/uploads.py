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
import re
import secrets
import smtplib
import time
from dataclasses import dataclass, field
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
# Each part URL is signed for one exact Content-Length, so a stalled client must
# re-initiate rather than reuse a long-lived signature.
_PRESIGN_EXPIRY_S = 30 * 60
_SESSION_TTL_S = 6 * 3600
_MAX_OPEN_UPLOADS_PER_USER = 3


def _sanitize_filename(name: str) -> str:
    base = (name or "upload.zip").rsplit("/", 1)[-1].rsplit("\\", 1)[-1]
    return _FILENAME_SAFE.sub("_", base)[-128:]


# ---------------------------------------------------------------------------
# In-process upload sessions
# ---------------------------------------------------------------------------
# The bytes never touch the gateway, so the only server-side record of what a
# principal was allowed to upload is this registry. It binds owner, expected
# total length and the per-part plan, and it is what the concurrent-bytes and
# open-upload caps are counted from. A gateway restart drops open sessions —
# clients must re-initiate; S3 lifecycle rules abort the orphaned uploads.


@dataclass
class _UploadSession:
    key: str
    upload_id: str
    user_id: str
    size_bytes: int
    part_lengths: list[int] = field(default_factory=list)
    expires_at: float = 0.0


_sessions: dict[str, _UploadSession] = {}


def _prune_sessions(now: float | None = None) -> None:
    cutoff = now if now is not None else time.monotonic()
    for key in [k for k, s in _sessions.items() if s.expires_at <= cutoff]:
        del _sessions[key]


def _part_plan(size_bytes: int) -> list[int]:
    full, remainder = divmod(size_bytes, PART_SIZE)
    plan = [PART_SIZE] * full
    if remainder or not plan:
        plan.append(remainder)
    return plan


def _check_quota(user_id: str, size_bytes: int, max_bytes: int) -> None:
    """Enforce per-principal open-upload and concurrent-byte ceilings."""
    _prune_sessions()
    open_sessions = [s for s in _sessions.values() if s.user_id == user_id]
    if len(open_sessions) >= _MAX_OPEN_UPLOADS_PER_USER:
        raise HTTPException(
            status_code=429,
            detail=f"Too many uploads in progress (limit {_MAX_OPEN_UPLOADS_PER_USER}) — finish or abort one first",
        )
    outstanding = sum(s.size_bytes for s in open_sessions)
    if outstanding + size_bytes > max_bytes:
        raise HTTPException(
            status_code=429,
            detail=f"Uploads in progress already reserve {outstanding // (1024 * 1024)} MB of the quota",
        )


def _owned_session(key: str, upload_id: str, user_id: str) -> _UploadSession:
    _prune_sessions()
    session = _sessions.get(key)
    if session is None or session.upload_id != upload_id or session.user_id != user_id:
        raise HTTPException(status_code=404, detail="Unknown or expired upload session")
    return session


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

        # Same scoped credentials/region as the S3 client — the container has
        # no ambient AWS region or role, so the default chain NoRegionErrors.
        ses_kwargs: dict = {}
        if cfg.s3_region:
            ses_kwargs["region_name"] = cfg.s3_region
        if cfg.s3_access_key and cfg.s3_secret_key:
            ses_kwargs["aws_access_key_id"] = cfg.s3_access_key
            ses_kwargs["aws_secret_access_key"] = cfg.s3_secret_key
        boto3.client("ses", **ses_kwargs).send_email(
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

    _check_quota(user_id, req.size_bytes, cfg.max_bytes)

    key, reference_id, _ = _new_key(filename)
    part_lengths = _part_plan(req.size_bytes)

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
        # ContentLength lands in X-Amz-SignedHeaders, so S3 rejects any part whose
        # body length differs from the plan — the claimed size becomes binding.
        part_urls = [
            signer.generate_presigned_url(
                "upload_part",
                Params={
                    "Bucket": cfg.bucket,
                    "Key": key,
                    "UploadId": upload_id,
                    "PartNumber": n,
                    "ContentLength": length,
                },
                ExpiresIn=_PRESIGN_EXPIRY_S,
            )
            for n, length in enumerate(part_lengths, start=1)
        ]
        return InitiateResponse(
            key=key,
            upload_id=upload_id,
            reference_id=reference_id,
            part_size=PART_SIZE,
            part_urls=part_urls,
        )

    response = await run_in_threadpool(_initiate)
    _sessions[key] = _UploadSession(
        key=key,
        upload_id=response.upload_id,
        user_id=user_id,
        size_bytes=req.size_bytes,
        part_lengths=part_lengths,
        expires_at=time.monotonic() + _SESSION_TTL_S,
    )
    return response


@router.post("/evals/upload/complete", dependencies=[RequireScope("write")])
async def complete_eval_upload(user_id: UserID, req: CompleteRequest):
    """Finish the multipart upload, verify size, and email the team."""
    cfg = _require_enabled()
    _validate_key(req.key)
    session = _owned_session(req.key, req.upload_id, user_id)

    highest = max(p.part_number for p in req.parts)
    if highest > len(session.part_lengths) or len({p.part_number for p in req.parts}) != len(req.parts):
        raise HTTPException(status_code=400, detail="Completed parts do not match the upload plan")

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
        if size > min(cfg.max_bytes, session.size_bytes):
            # Backstop behind the per-part signature: the object must not exceed
            # what the session reserved.
            client.delete_object(Bucket=cfg.bucket, Key=req.key)
            raise HTTPException(
                status_code=413,
                detail=f"Upload is {size // (1024 * 1024)} MB — larger than the {cfg.max_mb} MB limit or the declared size",
            )
        return size

    try:
        size = await run_in_threadpool(_complete)
    finally:
        _sessions.pop(req.key, None)

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


@router.post("/evals/upload/abort", status_code=204, response_model=None, dependencies=[RequireScope("write")])
async def abort_eval_upload(user_id: UserID, req: AbortRequest) -> None:
    """Best-effort cleanup when the client gives up; lifecycle rules are the backstop."""
    cfg = _require_enabled()
    _validate_key(req.key)
    _owned_session(req.key, req.upload_id, user_id)
    _sessions.pop(req.key, None)

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
