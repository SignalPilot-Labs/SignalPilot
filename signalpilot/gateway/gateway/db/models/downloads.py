"""Short-lived, single-use grants for private chat file downloads."""

from datetime import datetime

from sqlalchemy import BigInteger, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from .base import GatewayBase, TZDateTime


class GatewayArtifactDownload(GatewayBase):
    __tablename__ = "gateway_artifact_downloads"

    token_hash: Mapped[str] = mapped_column(String(64), primary_key=True)
    org_id: Mapped[str] = mapped_column(String, nullable=False)
    user_id: Mapped[str] = mapped_column(String, nullable=False)
    conversation_id: Mapped[str] = mapped_column(String, nullable=False)
    artifact_id: Mapped[str] = mapped_column(String, nullable=False)
    runtime_env: Mapped[str | None] = mapped_column(String(50))
    object_key: Mapped[str] = mapped_column(Text, nullable=False)
    filename: Mapped[str] = mapped_column(Text, nullable=False)
    byte_size: Mapped[int] = mapped_column(BigInteger, nullable=False)
    content_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    expires_at: Mapped[datetime] = mapped_column(TZDateTime, nullable=False, index=True)
