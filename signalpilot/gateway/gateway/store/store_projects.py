"""Projects, audit log, schema endorsements and PII redaction config."""

from __future__ import annotations

import gateway.store.audit_log as audit_log
import gateway.store.endorsements as endorsements_mod
import gateway.store.projects as projects
from gateway.models import (
    AuditEntry,
    ConnectionInfo,
)


class ProjectsStoreMixin:
    """Projects, audit log, schema endorsements and PII redaction config."""

    # Projects.

    async def list_projects(self) -> list[projects.ProjectInfo]:
        oid = self._require_org_id()
        return await projects.list_projects(self.session, org_id=oid)

    async def get_project(self, name: str) -> projects.ProjectInfo | None:
        oid = self._require_org_id()
        return await projects.get_project(self.session, org_id=oid, name=name)

    async def create_project(self, proj: projects.ProjectCreate) -> projects.ProjectInfo:
        oid = self._require_org_id()
        return await projects.create_project(
            self.session,
            org_id=oid,
            user_id=self.user_id,
            proj=proj,
            get_connection=self.get_connection,
            get_existing_project=self.get_project,
        )

    def _create_new_project(self, proj: projects.ProjectCreate, connection: ConnectionInfo) -> projects.ProjectInfo:
        return projects.create_new_project(proj, connection, org_id=self._require_org_id())

    def _create_local_project(self, proj: projects.ProjectCreate, connection: ConnectionInfo) -> projects.ProjectInfo:
        return projects.create_local_project(proj, connection, org_id=self._require_org_id())

    def _generate_profiles_yml(self, project_name: str, connection: ConnectionInfo) -> str:
        return projects.generate_profiles_yml(project_name, connection)

    async def update_project(self, name: str, update_data: projects.ProjectUpdate) -> projects.ProjectInfo | None:
        oid = self._require_org_id()
        return await projects.update_project(self.session, org_id=oid, name=name, update_data=update_data)

    async def delete_project(self, name: str) -> bool:
        oid = self._require_org_id()
        return await projects.delete_project(self.session, org_id=oid, name=name)

    # Audit.

    async def append_audit(self, entry: AuditEntry) -> None:
        oid = self._require_org_id()
        await audit_log.append_audit(self.session, org_id=oid, user_id=self.user_id, entry=entry)

    async def read_audit(
        self,
        limit: int = 200,
        offset: int = 0,
        connection_name: str | None = None,
        event_type: str | None = None,
        return_total: bool = False,
    ) -> list[AuditEntry] | tuple[list[AuditEntry], int]:
        oid = self._require_org_id()
        if self.eval_connection:
            connection_name = self.eval_connection
        return await audit_log.read_audit(
            self.session,
            org_id=oid,
            limit=limit,
            offset=offset,
            connection_name=connection_name,
            event_type=event_type,
            return_total=return_total,
        )

    # Schema Endorsements.

    async def get_schema_endorsements(self, name: str) -> dict:
        oid = self._require_org_id()
        return await endorsements_mod.get_schema_endorsements(self.session, org_id=oid, name=name)

    async def set_schema_endorsements(self, name: str, endorsements: dict) -> dict:
        oid = self._require_org_id()
        return await endorsements_mod.set_schema_endorsements(
            self.session, org_id=oid, name=name, endorsements=endorsements
        )

    # PII Redaction Config.

    async def get_pii_config(self, name: str) -> dict:
        oid = self._require_org_id()
        return await endorsements_mod.get_pii_config(self.session, org_id=oid, name=name)

    async def set_pii_config(self, name: str, enabled: bool, rules: dict[str, str]) -> dict:
        oid = self._require_org_id()
        return await endorsements_mod.set_pii_config(self.session, org_id=oid, name=name, enabled=enabled, rules=rules)

    async def delete_schema_endorsements(self, name: str):
        oid = self._require_org_id()
        return await endorsements_mod.delete_schema_endorsements(self.session, org_id=oid, name=name)

    async def apply_endorsement_filter(self, name: str, schema: dict) -> dict:
        oid = self._require_org_id()
        return await endorsements_mod.apply_endorsement_filter(self.session, org_id=oid, name=name, schema=schema)
