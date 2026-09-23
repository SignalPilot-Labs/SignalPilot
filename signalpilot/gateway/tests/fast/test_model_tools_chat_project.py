"""Project-reading MCP tools in a chat session, and dialect-aware audit SQL."""

from __future__ import annotations

import asyncio
import io
import tarfile

import pytest

from gateway.mcp.context import mcp_branch_var, mcp_org_id_var, mcp_project_id_var
from gateway.mcp.tools import model_map_workspace as ws
from gateway.mcp.tools.model_verify import _for_dialect

SANDBOX_DIR = "/home/notebook/.sp/projects/.standalone-chat/p/conv/dbt_proj"


def _tarball(files: dict[str, str]) -> bytes:
    buf = io.BytesIO()
    with tarfile.open(fileobj=buf, mode="w:gz") as tar:
        for name, text in files.items():
            data = text.encode()
            info = tarfile.TarInfo(name)
            info.size = len(data)
            tar.addfile(info, io.BytesIO(data))
    return buf.getvalue()


def test_dbt_directory_matches_the_sandbox_path_suffix(tmp_path):
    (tmp_path / "dbt_proj").mkdir()
    (tmp_path / "dbt_proj" / "dbt_project.yml").write_text("name: x")
    (tmp_path / "other").mkdir()
    (tmp_path / "other" / "dbt_project.yml").write_text("name: y")
    assert ws._dbt_directory(tmp_path, SANDBOX_DIR) == tmp_path / "dbt_proj"
    # Nothing matches and two candidates exist: refuse to guess.
    assert ws._dbt_directory(tmp_path, "/somewhere/else") is None


def test_extract_rejects_path_escape(tmp_path):
    with pytest.raises(ValueError):
        ws._extract(_tarball({"../evil.sql": "x"}), tmp_path / "rev-1")
    assert not (tmp_path / "rev-1").exists()


def test_extract_replaces_older_revisions(tmp_path):
    ws._extract(_tarball({"a/dbt_project.yml": "n"}), tmp_path / "rev-1")
    ws._extract(_tarball({"a/dbt_project.yml": "n"}), tmp_path / "rev-2")
    assert [p.name for p in tmp_path.iterdir()] == ["rev-2"]


def test_cloud_session_reads_the_pinned_project_snapshot(tmp_path, monkeypatch):
    monkeypatch.setenv("SP_DEPLOYMENT_MODE", "cloud")
    monkeypatch.delenv("SP_WORKSPACE_ROOT", raising=False)
    (tmp_path / "dbt_proj").mkdir()
    (tmp_path / "dbt_proj" / "dbt_project.yml").write_text("name: x")
    seen = {}

    async def fake_snapshot(org_id, project_id, branch):
        seen.update(org=org_id, project=project_id, branch=branch)
        return tmp_path

    monkeypatch.setattr(ws, "_snapshot_directory", fake_snapshot)

    async def run():
        mcp_project_id_var.set("p")
        mcp_org_id_var.set("org")
        mcp_branch_var.set("dev")
        return await ws.resolve_project_dir(SANDBOX_DIR)

    work_dir, err = asyncio.run(run())
    assert err is None
    assert work_dir == tmp_path / "dbt_proj"
    assert seen == {"org": "org", "project": "p", "branch": "dev"}


def test_cloud_without_a_project_pin_keeps_the_refusal(monkeypatch):
    monkeypatch.setenv("SP_DEPLOYMENT_MODE", "cloud")
    monkeypatch.delenv("SP_WORKSPACE_ROOT", raising=False)

    async def run():
        mcp_project_id_var.set(None)
        return await ws.resolve_project_dir(SANDBOX_DIR)

    work_dir, err = asyncio.run(run())
    assert work_dir is None
    assert "cannot read a sandbox project_dir" in err


def test_audit_sql_is_valid_tsql():
    scan = _for_dialect(
        'SELECT COUNT(*) - COUNT("c") AS nulls, COUNT(DISTINCT "c") AS dist FROM "A"."m"."t"',
        "mssql",
    )
    assert "FILTER" not in scan and "[c]" in scan
    assert _for_dialect('SELECT * FROM "A"."m"."t" LIMIT 5', "mssql") == "SELECT TOP 5 * FROM [A].[m].[t]"
    assert _for_dialect('SELECT * FROM "t" LIMIT 5', "postgres") == 'SELECT * FROM "t" LIMIT 5'
