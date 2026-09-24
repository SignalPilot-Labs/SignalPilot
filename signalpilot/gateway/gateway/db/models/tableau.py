"""Tableau integration: one org-scoped site + personal access token.

The gateway owns the PAT (Fernet-encrypted) and makes every Tableau REST and
VizQL Data Service call on behalf of chat runs. ``status`` is the result of
the last credential check; the integration is active for chat only when the
row exists, ``enabled`` is true, and ``status == "ok"``.
"""

from __future__ import annotations

import uuid

from sqlalchemy import Boolean, Float, LargeBinary, String, Text, UniqueConstraint, true
from sqlalchemy.orm import Mapped, mapped_column

from .base import GatewayBase


class GatewayTableauIntegration(GatewayBase):
    """Tableau site connection scoped by org (at most one per org)."""

    __tablename__ = "gateway_tableau_integrations"

    id: Mapped[str] = mapped_column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    org_id: Mapped[str] = mapped_column(String, nullable=False)
    server_url: Mapped[str] = mapped_column(String(255), nullable=False)
    site_content_url: Mapped[str] = mapped_column(String(255), nullable=False, default="", server_default="")
    pat_name: Mapped[str] = mapped_column(String(255), nullable=False)
    pat_secret_enc: Mapped[bytes] = mapped_column(LargeBinary, nullable=False)
    enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True, server_default=true())
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="unknown", server_default="unknown")
    last_error: Mapped[str | None] = mapped_column(Text, nullable=True)
    site_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    user_name: Mapped[str | None] = mapped_column(String(255), nullable=True)
    site_role: Mapped[str | None] = mapped_column(String(64), nullable=True)
    verified_at: Mapped[float | None] = mapped_column(Float, nullable=True)
    created_by: Mapped[str | None] = mapped_column(String, nullable=True)
    created_at: Mapped[float] = mapped_column(Float, nullable=False)
    updated_at: Mapped[float] = mapped_column(Float, nullable=False)

    __table_args__ = (UniqueConstraint("org_id", name="uq_gw_tableau_org"),)
