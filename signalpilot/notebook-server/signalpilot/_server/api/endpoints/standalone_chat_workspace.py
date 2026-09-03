"""Preparation and cleanup boundaries for a chat execution workspace."""

from __future__ import annotations

import asyncio
import shutil
from typing import TYPE_CHECKING

from signalpilot._server.api.endpoints.standalone_chat_runtime import (
    _execution_project_directory,
    _scratch_directory,
    _seed_analysis_notebook,
    _tree_digest,
)

if TYPE_CHECKING:
    from pathlib import Path


async def prepare_execution_workspace(
    *,
    run_id: str,
    conversation_id: str,
    project_id: str,
    branch: str,
    connection_name: str,
    gateway_url: str,
    gateway_token: str,
) -> tuple[Path, Path, str, Path, bool, str]:
    scratch = _scratch_directory(run_id)
    notebook_path = _seed_analysis_notebook(
        scratch=scratch,
        run_id=run_id,
        project_id=project_id,
        connection_name=connection_name,
        gateway_url=gateway_url,
        scoped_token=gateway_token,
    )
    seeded_source = notebook_path.read_text(encoding="utf-8")
    try:
        project_directory, remove_project_directory = (
            await _execution_project_directory(
                # Claude Agent SDK sessions are scoped to cwd. Keep this path
                # stable across turns while still rematerializing its contents
                # from the frozen snapshot for every run.
                run_id=conversation_id,
                project_id=project_id,
                branch=branch,
                gateway_url=gateway_url,
                gateway_token=gateway_token,
            )
        )
    except Exception:
        shutil.rmtree(scratch, ignore_errors=True)
        raise
    baseline_digest = await asyncio.to_thread(_tree_digest, project_directory)
    return (
        scratch,
        notebook_path,
        seeded_source,
        project_directory,
        remove_project_directory,
        baseline_digest,
    )
