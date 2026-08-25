"""API endpoints for dbt integration."""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING, Any

import msgspec
from starlette.authentication import requires
from starlette.responses import JSONResponse

from signalpilot import _loggers
from signalpilot._server.api.utils import parse_request
from signalpilot._server.files.path_confinement import (
    confine,
    confine_optional,
    workspace_roots,
)
from signalpilot._server.router import APIRouter

if TYPE_CHECKING:
    from starlette.requests import Request

LOGGER = _loggers.sp_logger()

router = APIRouter()


async def _resolve_start_dir(request: Any, body_dir: str | None) -> str | None:
    """Resolve the dbt start directory.

    S3 workspace mode: dbt is a subprocess and needs real files, so the branch
    head is materialized into execution scratch and the org-level
    dbt_project_dir setting (gateway-resolved: explicit setting wins, manifest
    auto-detect otherwise) names the directory inside it. Materialization is
    network+disk work and runs off the event loop. An explicit projectDir in
    the request body still overrides for local trees.
    """
    del request
    if body_dir:
        return str(confine(body_dir, label="projectDir"))

    from signalpilot._server.files.workspace import is_s3_workspace

    if is_s3_workspace():
        import asyncio

        from signalpilot._dbt.materialize import materialized_dbt_start_dir

        return await asyncio.to_thread(materialized_dbt_start_dir)
    return None


class DbtCommandRequest(msgspec.Struct, rename="camel"):
    command: str
    args: list[str] = msgspec.field(default_factory=list)
    project_dir: str | None = None
    profiles_dir: str | None = None
    target: str | None = None


class DbtCommandResponse(msgspec.Struct, rename="camel"):
    success: bool
    command: str
    exit_code: int
    stdout: str
    stderr: str
    duration_ms: float
    project_dir: str | None = None


class DbtProjectInfoResponse(msgspec.Struct, rename="camel"):
    success: bool
    found: bool
    project_dir: str | None = None
    project_name: str | None = None
    profile: str | None = None
    model_paths: list[str] = msgspec.field(default_factory=list)
    seed_paths: list[str] = msgspec.field(default_factory=list)
    test_paths: list[str] = msgspec.field(default_factory=list)
    macro_paths: list[str] = msgspec.field(default_factory=list)
    snapshot_paths: list[str] = msgspec.field(default_factory=list)
    has_manifest: bool = False
    has_profiles: bool = False
    dbt_version: str | None = None
    dbt_installed: bool = False


class DbtModelsResponse(msgspec.Struct, rename="camel"):
    success: bool
    models: list[dict[str, Any]] = msgspec.field(default_factory=list)
    project_dir: str | None = None


class DbtArtifactRequest(msgspec.Struct, rename="camel"):
    project_dir: str | None = None
    artifact: str = "manifest"


class DbtArtifactResponse(msgspec.Struct, rename="camel"):
    success: bool
    artifact: str
    data: dict[str, Any] | None = None
    error: str | None = None


@router.post("/command")
@requires("edit")
async def run_dbt_command(
    *,
    request: Request,
) -> DbtCommandResponse | JSONResponse:
    """
    requestBody:
        content:
            application/json:
                schema:
                    $ref: "#/components/schemas/DbtCommandRequest"
    responses:
        200:
            description: Run a dbt command
    """
    from signalpilot._dbt.runner import DBT_COMMANDS, run_dbt_command_async

    body = await parse_request(request, cls=DbtCommandRequest)

    if body.command.strip() not in DBT_COMMANDS:
        return JSONResponse(
            {"error": f"Unsupported dbt command: {body.command!r}"},
            status_code=400,
        )

    # Resolve project dir: explicit > cloud project > cwd
    project_dir = await _resolve_start_dir(request, body.project_dir)
    profiles_dir = confine_optional(body.profiles_dir, label="profilesDir")

    result = await run_dbt_command_async(
        command=body.command,
        args=body.args if body.args else None,
        project_dir=project_dir,
        profiles_dir=str(profiles_dir) if profiles_dir else None,
        target=body.target,
    )

    return DbtCommandResponse(
        success=result.success,
        command=result.command,
        exit_code=result.exit_code,
        stdout=result.stdout,
        stderr=result.stderr,
        duration_ms=result.duration_ms,
        project_dir=result.project_dir,
    )


@router.post("/project_info")
@requires("edit")
async def get_project_info(
    *,
    request: Request,
) -> DbtProjectInfoResponse:
    """
    requestBody:
        content:
            application/json:
                schema:
                    properties:
                        projectDir:
                            type: string
    responses:
        200:
            description: Get dbt project information
    """
    from signalpilot._dbt.runner import (
        find_dbt_executable,
        find_dbt_project,
        parse_dbt_project_yml,
    )

    body = await request.json()
    start_dir = await _resolve_start_dir(request, body.get("projectDir") if body else None)

    dbt_installed = find_dbt_executable() is not None
    project_dir = find_dbt_project(start_dir)

    if not project_dir:
        return DbtProjectInfoResponse(
            success=True,
            found=False,
            dbt_installed=dbt_installed,
        )

    info = parse_dbt_project_yml(project_dir)

    return DbtProjectInfoResponse(
        success=True,
        found=True,
        project_dir=info.project_dir,
        project_name=info.project_name,
        profile=info.profile,
        model_paths=info.model_paths,
        seed_paths=info.seed_paths,
        test_paths=info.test_paths,
        macro_paths=info.macro_paths,
        snapshot_paths=info.snapshot_paths,
        has_manifest=info.has_manifest,
        has_profiles=info.has_profiles,
        dbt_version=info.dbt_version,
        dbt_installed=dbt_installed,
    )


@router.post("/models")
@requires("edit")
async def get_models(
    *,
    request: Request,
) -> DbtModelsResponse:
    """
    requestBody:
        content:
            application/json:
                schema:
                    properties:
                        projectDir:
                            type: string
    responses:
        200:
            description: List dbt models from manifest
    """
    from signalpilot._dbt.runner import find_dbt_project, list_models

    body = await request.json()
    start_dir = await _resolve_start_dir(request, body.get("projectDir") if body else None)
    project_dir = find_dbt_project(start_dir)

    if not project_dir:
        return DbtModelsResponse(
            success=False,
            project_dir=None,
        )

    models = list_models(project_dir)
    return DbtModelsResponse(
        success=True,
        models=models,
        project_dir=project_dir,
    )


@router.post("/artifact")
@requires("edit")
async def get_artifact(
    *,
    request: Request,
) -> DbtArtifactResponse:
    """
    requestBody:
        content:
            application/json:
                schema:
                    $ref: "#/components/schemas/DbtArtifactRequest"
    responses:
        200:
            description: Get dbt artifact contents
    """
    from signalpilot._dbt.runner import (
        find_dbt_project,
        get_graph_summary,
        get_manifest,
        get_run_results,
    )

    body = await parse_request(request, cls=DbtArtifactRequest)
    project_dir = find_dbt_project(await _resolve_start_dir(request, body.project_dir))

    if not project_dir:
        return DbtArtifactResponse(
            success=False,
            artifact=body.artifact,
            error="No dbt project found",
        )

    if body.artifact == "manifest":
        data = get_manifest(project_dir)
    elif body.artifact == "run_results":
        data = get_run_results(project_dir)
    elif body.artifact == "graph_summary":
        data = get_graph_summary(project_dir)
    else:
        return DbtArtifactResponse(
            success=False,
            artifact=body.artifact,
            error=f"Unknown artifact: {body.artifact}",
        )

    if data is None:
        return DbtArtifactResponse(
            success=False,
            artifact=body.artifact,
            error=f"Artifact {body.artifact} not found. Run 'dbt parse' first.",
        )

    return DbtArtifactResponse(
        success=True,
        artifact=body.artifact,
        data=data,
    )


# ── Project discovery, scaffolding, and cloning ──────────────────


class DbtProjectSummary(msgspec.Struct, rename="camel"):
    project_dir: str
    project_name: str | None = None
    profile: str | None = None
    last_modified: float | None = None


class DbtDiscoverResponse(msgspec.Struct, rename="camel"):
    success: bool
    projects: list[DbtProjectSummary] = msgspec.field(default_factory=list)
    root_dir: str | None = None


class DbtScaffoldRequest(msgspec.Struct, rename="camel"):
    project_name: str
    parent_dir: str | None = None
    adapter: str = "duckdb"


class DbtScaffoldResponse(msgspec.Struct, rename="camel"):
    success: bool
    project_dir: str | None = None
    error: str | None = None
    files_created: list[str] = msgspec.field(default_factory=list)


class DbtCloneRequest(msgspec.Struct, rename="camel"):
    git_url: str
    target_dir: str | None = None
    branch: str | None = None


class DbtCloneResponse(msgspec.Struct, rename="camel"):
    success: bool
    project_dir: str | None = None
    project_name: str | None = None
    error: str | None = None


@router.post("/discover_projects")
@requires("edit")
async def discover_projects(
    *,
    request: Request,
) -> DbtDiscoverResponse:
    from signalpilot._dbt.runner import discover_dbt_projects

    body = await request.json()
    confined_root = confine_optional(
        body.get("rootDir") if body else None, label="rootDir"
    )
    root_dir = str(confined_root) if confined_root else None

    projects = discover_dbt_projects(root_dir)

    summaries = []
    for p in projects:
        last_modified = None
        yml = Path(p.project_dir) / "dbt_project.yml"
        if yml.exists():
            last_modified = yml.stat().st_mtime
        summaries.append(
            DbtProjectSummary(
                project_dir=p.project_dir,
                project_name=p.project_name,
                profile=p.profile,
                last_modified=last_modified,
            )
        )

    return DbtDiscoverResponse(
        success=True,
        projects=summaries,
        root_dir=root_dir or str(workspace_roots()[0]),
    )


@router.post("/scaffold_project")
@requires("edit")
async def scaffold_project(
    *,
    request: Request,
) -> DbtScaffoldResponse:
    from signalpilot._dbt.runner import scaffold_dbt_project

    body = await parse_request(request, cls=DbtScaffoldRequest)

    # Confined here rather than only in the runner: the try below swallows
    # exceptions into a 200 body, which would mask the rejection.
    confined_parent = confine_optional(body.parent_dir, label="parentDir")
    parent_dir = str(confined_parent) if confined_parent else None
    project_name = body.project_name
    if project_name != ".":
        confine(
            (confined_parent or workspace_roots()[0]) / project_name,
            label="projectName",
        )

    # If parentDir points to an existing git repo, scaffold in-place
    if parent_dir and (Path(parent_dir) / ".git").exists():
        project_name = "."
    elif not parent_dir:
        # Fallback: check cloud project dir
        cloud_dir = await _resolve_start_dir(request, None)
        if cloud_dir:
            parent_dir = cloud_dir
            project_name = "."

    try:
        project_dir, files_created = scaffold_dbt_project(
            project_name=project_name,
            parent_dir=parent_dir,
            adapter=body.adapter,
        )
        return DbtScaffoldResponse(
            success=True,
            project_dir=project_dir,
            files_created=files_created,
        )
    except Exception as e:
        return DbtScaffoldResponse(
            success=False,
            error=str(e),
        )


@router.post("/clone_project")
@requires("edit")
async def clone_project(
    *,
    request: Request,
) -> DbtCloneResponse | JSONResponse:
    import asyncio

    from signalpilot._dbt.runner import clone_git_repo, find_dbt_project, parse_dbt_project_yml

    body = await parse_request(request, cls=DbtCloneRequest)

    # http(s) only: ext:: and file:// transports are code-exec/exfil vectors
    if not body.git_url.strip().lower().startswith(("http://", "https://")):
        return JSONResponse(
            {"error": "Only http(s) git URLs are supported"},
            status_code=400,
        )

    target_dir = confine_optional(body.target_dir, label="targetDir")

    loop = asyncio.get_event_loop()
    success, cloned_dir, error = await loop.run_in_executor(
        None,
        lambda: clone_git_repo(
            git_url=body.git_url,
            target_dir=str(target_dir) if target_dir else None,
            branch=body.branch,
        ),
    )

    if not success:
        return DbtCloneResponse(
            success=False,
            error=error,
        )

    project_dir = find_dbt_project(cloned_dir)
    project_name = None
    if project_dir:
        info = parse_dbt_project_yml(project_dir)
        project_name = info.project_name

    return DbtCloneResponse(
        success=True,
        project_dir=project_dir or cloned_dir,
        project_name=project_name,
    )


# ── Model-scoped commands ────────────────────────────────────────


class DbtCompileModelRequest(msgspec.Struct, rename="camel"):
    project_dir: str | None = None
    model_name: str = ""


class DbtCompileModelResponse(msgspec.Struct, rename="camel"):
    success: bool
    compiled_sql: str = ""
    error: str | None = None


class DbtPreviewModelRequest(msgspec.Struct, rename="camel"):
    project_dir: str | None = None
    model_name: str = ""
    limit: int = 500


class DbtPreviewColumn(msgspec.Struct, rename="camel"):
    name: str
    type: str = "string"


class DbtPreviewModelResponse(msgspec.Struct, rename="camel"):
    success: bool
    columns: list[DbtPreviewColumn] = msgspec.field(default_factory=list)
    rows: list[list[str]] = msgspec.field(default_factory=list)
    row_count: int = 0
    error: str | None = None


def _resolve_project_dir(hint: str | None) -> str | None:
    """Resolve project dir from hint, falling back to discovery."""
    from signalpilot._dbt.runner import discover_dbt_projects, find_dbt_project

    if hint:
        result = find_dbt_project(str(confine(hint, label="projectDir")))
        if result:
            return result

    result = find_dbt_project()
    if result:
        return result

    projects = discover_dbt_projects(max_depth=3)
    return projects[0].project_dir if projects else None


@router.post("/compile_model")
@requires("edit")
async def compile_model_endpoint(
    *,
    request: Request,
) -> DbtCompileModelResponse:
    """Compile a single dbt model and return the compiled SQL."""
    import asyncio

    from signalpilot._dbt.runner import compile_model

    body = await parse_request(request, cls=DbtCompileModelRequest)
    project_dir = _resolve_project_dir(body.project_dir)

    if not project_dir:
        return DbtCompileModelResponse(
            success=False,
            error="No dbt project found",
        )

    loop = asyncio.get_event_loop()
    success, compiled_sql, error = await loop.run_in_executor(
        None,
        lambda: compile_model(body.model_name, project_dir),
    )

    return DbtCompileModelResponse(
        success=success,
        compiled_sql=compiled_sql,
        error=error or None,
    )


@router.post("/preview_model")
@requires("edit")
async def preview_model_endpoint(
    *,
    request: Request,
) -> DbtPreviewModelResponse:
    """Preview a dbt model's query results."""
    import asyncio

    from signalpilot._dbt.runner import preview_model

    body = await parse_request(request, cls=DbtPreviewModelRequest)
    project_dir = _resolve_project_dir(body.project_dir)

    if not project_dir:
        return DbtPreviewModelResponse(
            success=False,
            error="No dbt project found",
        )

    loop = asyncio.get_event_loop()
    result = await loop.run_in_executor(
        None,
        lambda: preview_model(body.model_name, project_dir, body.limit),
    )

    return DbtPreviewModelResponse(
        success=result["success"],
        columns=[DbtPreviewColumn(name=c["name"], type=c.get("type", "string")) for c in result["columns"]],
        rows=result["rows"],
        row_count=result["rowCount"],
        error=result.get("error"),
    )
