"""Tests for MCP tool functions in gateway/mcp/tools/notebooks/.

Follows the pattern from test_mcp_server.py: patch gateway.mcp.context.get_session_factory
and gateway.mcp.context.Store (the internals used by _store_session), then set contextvars
before calling tool functions directly.

The @audited_tool decorator fires asyncio.create_task for audit logging — this will fail
silently in tests (expected and acceptable).
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from gateway.mcp import mcp_org_id_var, mcp_user_id_var
from gateway.models.notebooks import ImportCount, NotebookInfo, NotebookSummary

_VALID_UUID = "aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee"
_SECOND_UUID = "11111111-2222-3333-4444-555555555555"

_SAMPLE_NB_DICT = {
    "cells": [{"cell_type": "code", "source": "import os", "outputs": [], "metadata": {}}],
    "metadata": {"kernelspec": {"name": "python3"}},
    "nbformat": 4,
    "nbformat_minor": 5,
}

_SAMPLE_ANALYSIS = {
    "cell_counts": {"code": 1},
    "imports": ["os"],
    "execution_order_gaps": [],
    "error_cells": [],
    "output_summary": {},
    "total_code_lines": 1,
    "functions_defined": [],
    "kernel_info": None,
}


def _make_notebook_info(
    notebook_id: str = _VALID_UUID,
    name: str = "Test Notebook",
    analyzed_at: float | None = None,
) -> NotebookInfo:
    return NotebookInfo(
        id=notebook_id,
        name=name,
        description="",
        tags=[],
        cell_count=1,
        code_cell_count=1,
        markdown_cell_count=0,
        kernel_name="python3",
        created_at=1_000_000.0,
        updated_at=1_000_000.0,
        analyzed_at=analyzed_at,
    )


def _make_mock_store() -> MagicMock:
    store = MagicMock()
    store.list_notebooks = AsyncMock(return_value=[])
    store.count_notebooks = AsyncMock(return_value=0)
    store.get_notebook_meta = AsyncMock(return_value=None)
    store.create_notebook = AsyncMock(return_value=_make_notebook_info())
    store.update_notebook_analysis = AsyncMock(return_value=True)
    store.delete_notebook_meta = AsyncMock(return_value=False)
    store.update_notebook_metadata = AsyncMock(return_value=None)
    store.search_notebooks = AsyncMock(return_value=[])
    store.get_notebook_analysis_json = AsyncMock(return_value=None)
    store.get_notebooks_summary = AsyncMock(return_value=NotebookSummary(
        total_notebooks=5,
        total_cells=20,
        total_code_cells=15,
        total_markdown_cells=5,
        total_code_lines=100,
        analyzed_count=3,
        pending_count=2,
        notebooks_with_errors=1,
        total_error_cells=2,
        top_imports=[ImportCount(name="numpy", count=3)],
    ))
    store.batch_delete_notebooks = AsyncMock(return_value=[])
    return store


def _make_store_patches(mock_store: MagicMock):
    """Return context manager patches for _store_session internals."""
    mock_session_cm = MagicMock()
    mock_session_cm.__aenter__ = AsyncMock(return_value=mock_session_cm)
    mock_session_cm.__aexit__ = AsyncMock(return_value=None)
    mock_factory = MagicMock(return_value=mock_session_cm)

    return (
        patch("gateway.mcp.context.get_session_factory", return_value=mock_factory),
        patch("gateway.mcp.context.Store", return_value=mock_store),
    )


class TestMCPListNotebooks:
    @pytest.mark.asyncio
    async def test_list_notebooks_empty(self) -> None:
        from gateway.mcp.tools.notebooks.crud import list_notebooks

        mock_store = _make_mock_store()
        mock_store.list_notebooks.return_value = []

        token_org = mcp_org_id_var.set("test-org")
        token_user = mcp_user_id_var.set("test-user")
        p1, p2 = _make_store_patches(mock_store)
        try:
            with p1, p2:
                result = await list_notebooks()
        finally:
            mcp_org_id_var.reset(token_org)
            mcp_user_id_var.reset(token_user)

        assert "No notebooks found" in result

    @pytest.mark.asyncio
    async def test_list_notebooks_with_results(self) -> None:
        from gateway.mcp.tools.notebooks.crud import list_notebooks

        mock_store = _make_mock_store()
        mock_store.list_notebooks.return_value = [_make_notebook_info()]

        token_org = mcp_org_id_var.set("test-org")
        token_user = mcp_user_id_var.set("test-user")
        p1, p2 = _make_store_patches(mock_store)
        try:
            with p1, p2:
                result = await list_notebooks()
        finally:
            mcp_org_id_var.reset(token_org)
            mcp_user_id_var.reset(token_user)

        assert "Test Notebook" in result

    @pytest.mark.asyncio
    async def test_list_notebooks_invalid_sort(self) -> None:
        from gateway.mcp.tools.notebooks.crud import list_notebooks

        token_org = mcp_org_id_var.set("test-org")
        token_user = mcp_user_id_var.set("test-user")
        try:
            result = await list_notebooks(sort_by="invalid")
        finally:
            mcp_org_id_var.reset(token_org)
            mcp_user_id_var.reset(token_user)

        assert "Error" in result


class TestMCPUploadNotebook:
    @pytest.mark.asyncio
    async def test_upload_success(self) -> None:
        from gateway.mcp.tools.notebooks.crud import upload_notebook

        mock_store = _make_mock_store()
        info = _make_notebook_info()
        mock_store.create_notebook.return_value = info

        token_org = mcp_org_id_var.set("test-org")
        token_user = mcp_user_id_var.set("test-user")
        p1, p2 = _make_store_patches(mock_store)
        import json as _json
        nb_content = _json.dumps(_SAMPLE_NB_DICT)
        try:
            with (
                p1,
                p2,
                patch("gateway.mcp.tools.notebooks.crud._save_notebook_file"),
                patch("gateway.mcp.tools.notebooks.crud._parse_notebook", return_value={
                    "cell_count": 1,
                    "code_cell_count": 1,
                    "markdown_cell_count": 0,
                    "kernel_name": "python3",
                }),
                patch("gateway.mcp.tools.notebooks.crud._analyze_notebook_content", return_value=_SAMPLE_ANALYSIS),
            ):
                result = await upload_notebook(name="My NB", content=nb_content)
        finally:
            mcp_org_id_var.reset(token_org)
            mcp_user_id_var.reset(token_user)

        assert "uploaded" in result.lower()

    @pytest.mark.asyncio
    async def test_upload_invalid_json(self) -> None:
        from gateway.mcp.tools.notebooks.crud import upload_notebook

        token_org = mcp_org_id_var.set("test-org")
        token_user = mcp_user_id_var.set("test-user")
        try:
            result = await upload_notebook(name="Bad", content="not json")
        finally:
            mcp_org_id_var.reset(token_org)
            mcp_user_id_var.reset(token_user)

        assert "Error" in result

    @pytest.mark.asyncio
    async def test_upload_name_too_long(self) -> None:
        from gateway.mcp.tools.notebooks.crud import upload_notebook

        token_org = mcp_org_id_var.set("test-org")
        token_user = mcp_user_id_var.set("test-user")
        try:
            result = await upload_notebook(name="x" * 121, content="{}")
        finally:
            mcp_org_id_var.reset(token_org)
            mcp_user_id_var.reset(token_user)

        assert "Error" in result


class TestMCPGetNotebook:
    @pytest.mark.asyncio
    async def test_get_found(self) -> None:
        from gateway.mcp.tools.notebooks.crud import get_notebook

        mock_store = _make_mock_store()
        mock_store.get_notebook_meta.return_value = _make_notebook_info()

        token_org = mcp_org_id_var.set("test-org")
        token_user = mcp_user_id_var.set("test-user")
        p1, p2 = _make_store_patches(mock_store)
        try:
            with (
                p1,
                p2,
                patch("gateway.mcp.tools.notebooks.crud._load_notebook_file", return_value=_SAMPLE_NB_DICT),
            ):
                result = await get_notebook(_VALID_UUID)
        finally:
            mcp_org_id_var.reset(token_org)
            mcp_user_id_var.reset(token_user)

        assert "Test Notebook" in result

    @pytest.mark.asyncio
    async def test_get_invalid_uuid(self) -> None:
        from gateway.mcp.tools.notebooks.crud import get_notebook

        token_org = mcp_org_id_var.set("test-org")
        token_user = mcp_user_id_var.set("test-user")
        try:
            result = await get_notebook("bad-id")
        finally:
            mcp_org_id_var.reset(token_org)
            mcp_user_id_var.reset(token_user)

        assert "Error" in result

    @pytest.mark.asyncio
    async def test_get_not_found(self) -> None:
        from gateway.mcp.tools.notebooks.crud import get_notebook

        mock_store = _make_mock_store()
        mock_store.get_notebook_meta.return_value = None

        token_org = mcp_org_id_var.set("test-org")
        token_user = mcp_user_id_var.set("test-user")
        p1, p2 = _make_store_patches(mock_store)
        try:
            with p1, p2:
                result = await get_notebook(_VALID_UUID)
        finally:
            mcp_org_id_var.reset(token_org)
            mcp_user_id_var.reset(token_user)

        assert "not found" in result.lower()


class TestMCPDeleteNotebook:
    @pytest.mark.asyncio
    async def test_delete_found(self) -> None:
        from gateway.mcp.tools.notebooks.crud import delete_notebook

        mock_store = _make_mock_store()
        mock_store.delete_notebook_meta.return_value = True

        token_org = mcp_org_id_var.set("test-org")
        token_user = mcp_user_id_var.set("test-user")
        p1, p2 = _make_store_patches(mock_store)
        try:
            with (
                p1,
                p2,
                patch("gateway.mcp.tools.notebooks.crud._delete_notebook_file"),
            ):
                result = await delete_notebook(_VALID_UUID)
        finally:
            mcp_org_id_var.reset(token_org)
            mcp_user_id_var.reset(token_user)

        assert "deleted" in result.lower()

    @pytest.mark.asyncio
    async def test_delete_not_found(self) -> None:
        from gateway.mcp.tools.notebooks.crud import delete_notebook

        mock_store = _make_mock_store()
        mock_store.delete_notebook_meta.return_value = False

        token_org = mcp_org_id_var.set("test-org")
        token_user = mcp_user_id_var.set("test-user")
        p1, p2 = _make_store_patches(mock_store)
        try:
            with p1, p2:
                result = await delete_notebook(_VALID_UUID)
        finally:
            mcp_org_id_var.reset(token_org)
            mcp_user_id_var.reset(token_user)

        assert "not found" in result.lower()


class TestMCPAnalyzeNotebook:
    @pytest.mark.asyncio
    async def test_analyze_success(self) -> None:
        from gateway.mcp.tools.notebooks.analysis import analyze_notebook

        mock_store = _make_mock_store()
        mock_store.update_notebook_analysis.return_value = True

        token_org = mcp_org_id_var.set("test-org")
        token_user = mcp_user_id_var.set("test-user")
        p1, p2 = _make_store_patches(mock_store)
        try:
            with (
                p1,
                p2,
                patch("gateway.mcp.tools.notebooks.analysis._load_notebook_file", return_value=_SAMPLE_NB_DICT),
                patch("gateway.mcp.tools.notebooks.analysis._analyze_notebook_content", return_value=_SAMPLE_ANALYSIS),
            ):
                result = await analyze_notebook(_VALID_UUID)
        finally:
            mcp_org_id_var.reset(token_org)
            mcp_user_id_var.reset(token_user)

        assert "Analysis for notebook" in result

    @pytest.mark.asyncio
    async def test_analyze_invalid_uuid(self) -> None:
        from gateway.mcp.tools.notebooks.analysis import analyze_notebook

        token_org = mcp_org_id_var.set("test-org")
        token_user = mcp_user_id_var.set("test-user")
        try:
            result = await analyze_notebook("bad-id")
        finally:
            mcp_org_id_var.reset(token_org)
            mcp_user_id_var.reset(token_user)

        assert "Error" in result


class TestMCPSearchNotebooks:
    @pytest.mark.asyncio
    async def test_search_found(self) -> None:
        from gateway.mcp.tools.notebooks.analysis import search_notebooks

        mock_store = _make_mock_store()
        mock_store.search_notebooks.return_value = [_make_notebook_info()]

        token_org = mcp_org_id_var.set("test-org")
        token_user = mcp_user_id_var.set("test-user")
        p1, p2 = _make_store_patches(mock_store)
        try:
            with p1, p2:
                result = await search_notebooks(query="test")
        finally:
            mcp_org_id_var.reset(token_org)
            mcp_user_id_var.reset(token_user)

        assert "Test Notebook" in result

    @pytest.mark.asyncio
    async def test_search_empty_query(self) -> None:
        from gateway.mcp.tools.notebooks.analysis import search_notebooks

        token_org = mcp_org_id_var.set("test-org")
        token_user = mcp_user_id_var.set("test-user")
        try:
            result = await search_notebooks(query="")
        finally:
            mcp_org_id_var.reset(token_org)
            mcp_user_id_var.reset(token_user)

        assert "Error" in result


class TestMCPBatchOperations:
    @pytest.mark.asyncio
    async def test_batch_analyze_success(self) -> None:
        from gateway.mcp.tools.notebooks.batch import batch_analyze_notebooks

        mock_store = _make_mock_store()
        mock_store.get_notebook_meta.return_value = _make_notebook_info()
        mock_store.update_notebook_analysis.return_value = True

        token_org = mcp_org_id_var.set("test-org")
        token_user = mcp_user_id_var.set("test-user")
        p1, p2 = _make_store_patches(mock_store)
        try:
            with (
                p1,
                p2,
                patch("gateway.mcp.tools.notebooks.batch._load_notebook_file", return_value=_SAMPLE_NB_DICT),
                patch("gateway.mcp.tools.notebooks.batch._analyze_notebook_content", return_value=_SAMPLE_ANALYSIS),
            ):
                result = await batch_analyze_notebooks(notebook_ids=_VALID_UUID)
        finally:
            mcp_org_id_var.reset(token_org)
            mcp_user_id_var.reset(token_user)

        assert "succeeded" in result

    @pytest.mark.asyncio
    async def test_batch_delete_success(self) -> None:
        from gateway.mcp.tools.notebooks.batch import batch_delete_notebooks

        mock_store = _make_mock_store()
        mock_store.batch_delete_notebooks.return_value = [(_VALID_UUID, True, None)]

        token_org = mcp_org_id_var.set("test-org")
        token_user = mcp_user_id_var.set("test-user")
        p1, p2 = _make_store_patches(mock_store)
        try:
            with (
                p1,
                p2,
                patch("gateway.mcp.tools.notebooks.batch._delete_notebook_file"),
            ):
                result = await batch_delete_notebooks(notebook_ids=_VALID_UUID)
        finally:
            mcp_org_id_var.reset(token_org)
            mcp_user_id_var.reset(token_user)

        assert "deleted" in result

    @pytest.mark.asyncio
    async def test_batch_invalid_uuid(self) -> None:
        from gateway.mcp.tools.notebooks.batch import batch_analyze_notebooks

        token_org = mcp_org_id_var.set("test-org")
        token_user = mcp_user_id_var.set("test-user")
        try:
            result = await batch_analyze_notebooks(notebook_ids="bad-id")
        finally:
            mcp_org_id_var.reset(token_org)
            mcp_user_id_var.reset(token_user)

        assert "Error" in result


class TestMCPCompareNotebooks:
    @pytest.mark.asyncio
    async def test_compare_success(self) -> None:
        from gateway.mcp.tools.notebooks.compare import compare_notebooks

        left_meta = _make_notebook_info(_VALID_UUID, "Left")
        right_meta = _make_notebook_info(_SECOND_UUID, "Right")

        mock_store = _make_mock_store()
        mock_store.get_notebook_meta.side_effect = lambda nid: left_meta if nid == _VALID_UUID else right_meta
        mock_store.get_notebook_analysis_json.return_value = None

        token_org = mcp_org_id_var.set("test-org")
        token_user = mcp_user_id_var.set("test-user")
        p1, p2 = _make_store_patches(mock_store)
        try:
            with (
                p1,
                p2,
                patch("gateway.mcp.tools.notebooks.compare._load_notebook_file", return_value=_SAMPLE_NB_DICT),
            ):
                result = await compare_notebooks(_VALID_UUID, _SECOND_UUID)
        finally:
            mcp_org_id_var.reset(token_org)
            mcp_user_id_var.reset(token_user)

        assert "Notebook Comparison" in result

    @pytest.mark.asyncio
    async def test_compare_self(self) -> None:
        from gateway.mcp.tools.notebooks.compare import compare_notebooks

        token_org = mcp_org_id_var.set("test-org")
        token_user = mcp_user_id_var.set("test-user")
        try:
            result = await compare_notebooks(_VALID_UUID, _VALID_UUID)
        finally:
            mcp_org_id_var.reset(token_org)
            mcp_user_id_var.reset(token_user)

        assert "Cannot compare" in result


class TestMCPGetNotebookReport:
    @pytest.mark.asyncio
    async def test_get_report_success(self) -> None:
        from gateway.mcp.tools.notebooks.report import get_notebook_report

        mock_store = _make_mock_store()
        mock_store.get_notebook_meta.return_value = _make_notebook_info()
        mock_store.get_notebook_analysis_json.return_value = None

        token_org = mcp_org_id_var.set("test-org")
        token_user = mcp_user_id_var.set("test-user")
        p1, p2 = _make_store_patches(mock_store)
        try:
            with (
                p1,
                p2,
                patch("gateway.mcp.tools.notebooks.report._load_notebook_file", return_value=_SAMPLE_NB_DICT),
            ):
                result = await get_notebook_report(_VALID_UUID)
        finally:
            mcp_org_id_var.reset(token_org)
            mcp_user_id_var.reset(token_user)

        assert "Notebook Report" in result
        assert "Test Notebook" in result

    @pytest.mark.asyncio
    async def test_get_report_invalid_uuid(self) -> None:
        from gateway.mcp.tools.notebooks.report import get_notebook_report

        token_org = mcp_org_id_var.set("test-org")
        token_user = mcp_user_id_var.set("test-user")
        try:
            result = await get_notebook_report("bad-uuid")
        finally:
            mcp_org_id_var.reset(token_org)
            mcp_user_id_var.reset(token_user)

        assert "Error" in result


class TestMCPUpdateNotebookMetadata:
    @pytest.mark.asyncio
    async def test_update_name_success(self) -> None:
        from gateway.mcp.tools.notebooks.crud import update_notebook_metadata

        updated = _make_notebook_info(name="New Name")
        mock_store = _make_mock_store()
        mock_store.update_notebook_metadata.return_value = updated

        token_org = mcp_org_id_var.set("test-org")
        token_user = mcp_user_id_var.set("test-user")
        p1, p2 = _make_store_patches(mock_store)
        try:
            with p1, p2:
                result = await update_notebook_metadata(notebook_id=_VALID_UUID, name="New Name")
        finally:
            mcp_org_id_var.reset(token_org)
            mcp_user_id_var.reset(token_user)

        assert "updated" in result.lower()

    @pytest.mark.asyncio
    async def test_update_no_fields(self) -> None:
        from gateway.mcp.tools.notebooks.crud import update_notebook_metadata

        token_org = mcp_org_id_var.set("test-org")
        token_user = mcp_user_id_var.set("test-user")
        try:
            result = await update_notebook_metadata(notebook_id=_VALID_UUID)
        finally:
            mcp_org_id_var.reset(token_org)
            mcp_user_id_var.reset(token_user)

        assert "Error" in result
