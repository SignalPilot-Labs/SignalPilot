"""Who created which Xata branch through the gateway.

Xata itself does not record the SignalPilot user behind a control-plane
call, so the gateway keeps one row per branch it creates. The row is the
creator-or-admin rule's evidence on delete: a member may delete only the
branches they created; an admin may delete any. A branch with no row was
not created through the gateway (or predates this table) and only an admin
may delete it.
"""

from __future__ import annotations

import uuid

from sqlalchemy import Float, Index, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from .base import GatewayBase


class GatewayXataBranchOwner(GatewayBase):
    __tablename__ = "gateway_xata_branch_owners"

    id: Mapped[str] = mapped_column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    org_id: Mapped[str] = mapped_column(String, nullable=False)
    connection_name: Mapped[str] = mapped_column(String(64), nullable=False)
    project: Mapped[str] = mapped_column(String(64), nullable=False)
    branch: Mapped[str] = mapped_column(String(64), nullable=False)
    created_by: Mapped[str] = mapped_column(String, nullable=False)
    created_at: Mapped[float] = mapped_column(Float, nullable=False)

    __table_args__ = (
        UniqueConstraint("org_id", "connection_name", "project", "branch", name="uq_gw_xata_branch_owner"),
        Index("ix_gw_xata_branch_owners_org", "org_id"),
    )
