"""Store class: all DB-backed operations scoped by org_id."""

from __future__ import annotations

import logging

from sqlalchemy.ext.asyncio import AsyncSession

import gateway.store.audit_log as audit_log  # noqa: F401  (patch target: gateway.store.store.audit_log)
import gateway.store.settings as settings_mod
from gateway.governance.context import current_org_id_var
from gateway.models import (
    GatewaySettings,
)
from gateway.runtime.mode import is_cloud_mode
from gateway.store.store_connections import ConnectionsStoreMixin
from gateway.store.store_integrations import IntegrationsStoreMixin
from gateway.store.store_knowledge import KnowledgeStoreMixin
from gateway.store.store_projects import ProjectsStoreMixin
from gateway.store.store_workspace import WorkspaceStoreMixin

logger = logging.getLogger(__name__)


# ═══════════════════════════════════════════════════════════════════════════════
# Store class: all DB-backed operations scoped by user_id
# ═══════════════════════════════════════════════════════════════════════════════


class Store(
    ConnectionsStoreMixin,
    ProjectsStoreMixin,
    IntegrationsStoreMixin,
    KnowledgeStoreMixin,
    WorkspaceStoreMixin,
):
    """Database-backed store scoped by org_id.

    Pass allow_unscoped=True for background tasks that legitimately need
    access across all orgs.  Callers that omit org_id without allow_unscoped=True
    will get a ValueError from _conn_filter to prevent accidental data leaks.
    """

    def __init__(
        self,
        session: AsyncSession,
        org_id: str | None = None,
        user_id: str | None = None,
        allow_unscoped: bool = False,
        eval_connection: str | None = None,
        allowed_connection_name: str | None = None,
        execution_identity: str | None = None,
    ):
        self.session = session
        self.org_id = org_id
        self.user_id = user_id
        self._allow_unscoped = allow_unscoped
        self.eval_connection = eval_connection
        self.allowed_connection_name = allowed_connection_name
        self.execution_identity = execution_identity
        # Intentional: we do not store the token for reset. FastAPI runs each request in a
        # dedicated asyncio task whose contextvars copy is isolated; the var dies with the task.
        # Background task usage must set the var explicitly and reset (see main.py schema refresh loop).
        if self.org_id:
            current_org_id_var.set(self.org_id)

    def _require_org_id(self) -> str:
        """Return org_id, raising ValueError in cloud mode if unset."""
        if self.org_id:
            return self.org_id
        if is_cloud_mode() and not self._allow_unscoped:
            raise ValueError(
                "org_id is required in cloud mode but was not set. Ensure resolve_org_id ran before constructing Store."
            )
        return "local"

    # Settings.

    async def load_settings(self) -> GatewaySettings:
        oid = self._require_org_id()
        return await settings_mod.load_settings(self.session, org_id=oid)

    async def save_settings(self, settings: GatewaySettings):
        oid = self._require_org_id()
        await settings_mod.save_settings(self.session, org_id=oid, user_id=self.user_id, settings=settings)
