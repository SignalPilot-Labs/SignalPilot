"""Project management tools: create_project, list_projects, get_project (cloud-gated)."""

from __future__ import annotations

from gateway.errors.mcp import sanitize_mcp_error
from gateway.mcp.audit import audited_tool
from gateway.mcp.context import _is_cloud, _store_session
from gateway.mcp.server import mcp

if not _is_cloud:

    @audited_tool(mcp)
    async def create_project(name: str, connection_name: str) -> str:
        """Create a new dbt project wired to an existing connection."""
        from gateway.models import ProjectCreate, ProjectSource

        try:
            proj = ProjectCreate(
                name=name,
                connection_name=connection_name,
                source=ProjectSource.new,
            )
            async with _store_session() as store:
                info = await store.create_project(proj)
        except ValueError as e:
            return f"Error: {sanitize_mcp_error(str(e))}"
        return (
            f"Created project '{info.name}' at {info.project_dir}\n"
            f"  connection: {info.connection_name}\n"
            f"  db_type: {info.db_type}\n"
            f"  storage: {info.storage.value}"
        )

    @audited_tool(mcp)
    async def list_projects() -> str:
        """List all configured dbt projects."""
        async with _store_session() as store:
            projects = await store.list_projects()
        if not projects:
            return "No projects configured."
        lines = [f"Found {len(projects)} project(s):\n"]
        for p in projects:
            lines.append(
                f"  - {p.name}  ({p.db_type}, {p.status.value})  connection={p.connection_name}  models={p.model_count}"
            )
        return "\n".join(lines)

    @audited_tool(mcp)
    async def get_project(name: str) -> str:
        """Get dbt project detail including path and model count."""
        async with _store_session() as store:
            proj = await store.get_project(name)
        if not proj:
            return f"Error: Project '{name}' not found."
        lines = [
            f"Project: {proj.name}",
            f"  id: {proj.id}",
            f"  connection: {proj.connection_name}",
            f"  db_type: {proj.db_type}",
            f"  project_dir: {proj.project_dir}",
            f"  storage: {proj.storage.value}",
            f"  source: {proj.source.value}",
            f"  status: {proj.status.value}",
            f"  model_count: {proj.model_count}",
            f"  dbt_version: {proj.dbt_version}",
        ]
        if proj.description:
            lines.append(f"  description: {proj.description}")
        if proj.tags:
            lines.append(f"  tags: {', '.join(proj.tags)}")
        if proj.git_remote:
            lines.append(f"  git_remote: {proj.git_remote}")
        return "\n".join(lines)
