"""Agent notebooks listing — powers the web app's Notebooks page.

Agent-generated notebooks are ordinary workspace-store files under the
reserved ``signalpilot-agent/`` prefix, committed by the runtime's headless
run endpoint. This API just aggregates them across the org's projects so the
UI has one list to render; opening one goes through the normal editor
(outputs replay from the committed session sidecar, no kernel needed).
"""

from __future__ import annotations

from fastapi import APIRouter

from ..auth import DBSession, OrgID, UserID
from ..security.scope_guard import RequireScope
from ..workspace_store.store import RevisionNotFound
from .deps import StoreD
from .workspace_files import WorkspaceStoreD

router = APIRouter()

AGENT_PREFIX = "signalpilot-agent/"


@router.get("/agent-notebooks", dependencies=[RequireScope("read")])
async def list_agent_notebooks(
    org_id: OrgID,
    _user: UserID,
    db: DBSession,
    store: StoreD,
    ws: WorkspaceStoreD,
):
    """Every signalpilot-agent/ notebook across the org's active projects."""
    projects, _total = await store.list_workspace_projects(
        status="active", limit=100, offset=0
    )
    notebooks = []
    for project in projects:
        project_id = getattr(project, "id", None) or project.get("id")
        project_name = (
            getattr(project, "display_name", None)
            or getattr(project, "name", None)
            or (project.get("display_name") or project.get("name") if isinstance(project, dict) else None)
            or ""
        )
        try:
            manifest = await ws.load_manifest(
                db, org_id=org_id, project_id=str(project_id), branch="main", revision=None
            )
        except RevisionNotFound:
            continue
        for entry in manifest.entries:
            if not entry.path.startswith(AGENT_PREFIX):
                continue
            if not entry.path.endswith(".py"):
                continue
            notebooks.append({
                "project_id": str(project_id),
                "project_name": project_name,
                "path": entry.path,
                "name": entry.path[len(AGENT_PREFIX):],
                "mtime": entry.mtime,
                "size": entry.size,
                "revision": manifest.revision,
                "has_outputs": any(
                    e.path == f"{AGENT_PREFIX}__sp__/session/{entry.path.rsplit('/', 1)[-1]}.json"
                    for e in manifest.entries
                ),
            })
    notebooks.sort(key=lambda n: n["mtime"] or 0, reverse=True)
    return {"notebooks": notebooks}
