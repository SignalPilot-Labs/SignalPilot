"""Eval upload endpoint — accepts a .zip, stores it in S3, notifies the team.

Deliberately minimal (see eval-upload-spec.md at repo root): no database rows,
no download path, no processing. S3 is the record; a bucket lifecycle rule
handles the 7-day deletion; the notification is one email.
"""

from __future__ import annotations

import logging
import re
import secrets
import smtplib
from datetime import UTC, datetime, timedelta
from email.message import EmailMessage

from fastapi import APIRouter, Form, HTTPException, UploadFile
from starlette.concurrency import run_in_threadpool

from ..auth import UserID
from ..config.uploads import EvalUploadsSettings, get_eval_uploads_settings
from ..security.scope_guard import RequireScope

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api")

_FILENAME_SAFE = re.compile(r"[^a-zA-Z0-9._-]")


def _sanitize_filename(name: str) -> str:
    base = (name or "upload.zip").rsplit("/", 1)[-1].rsplit("\\", 1)[-1]
    return _FILENAME_SAFE.sub("_", base)[-128:]


def _s3_client(cfg: EvalUploadsSettings):
    import boto3
    from botocore.config import Config

    kwargs: dict = {"config": Config(s3={"addressing_style": "path"})}
    if cfg.s3_endpoint:
        kwargs["endpoint_url"] = cfg.s3_endpoint
    if cfg.s3_access_key and cfg.s3_secret_key:
        kwargs["aws_access_key_id"] = cfg.s3_access_key
        kwargs["aws_secret_access_key"] = cfg.s3_secret_key
        kwargs["region_name"] = "us-east-1"
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


@router.post("/evals/upload", status_code=201, dependencies=[RequireScope("write")])
async def upload_eval(user_id: UserID, file: UploadFile, notes: str = Form("")):
    """Store an uploaded eval .zip in S3 and email the team."""
    cfg = get_eval_uploads_settings()
    if not cfg.enabled:
        raise HTTPException(status_code=404, detail="Eval uploads are not enabled")

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

    now = datetime.now(UTC)
    short_id = secrets.token_hex(4)
    key = f"uploads/{now:%Y-%m-%d}/{short_id}/{filename}"
    reference_id = f"eval-{now:%Y%m%d}-{short_id}"
    expires = f"{now + timedelta(days=7):%Y-%m-%d}"
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
                # S3 metadata must be ASCII — notes travel in full via the email.
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
        # The upload is the thing that matters; a lost email is recoverable
        # from the S3 listing.
        logger.exception("Eval upload notification failed (upload succeeded: %s)", key)

    return {"reference_id": reference_id, "expires_at": expires}
