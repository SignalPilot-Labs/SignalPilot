"""REST API endpoint tests for /api/notebooks.

Uses TestClient with get_store overridden to avoid real DB connections.
"""

from __future__ import annotations

import json
from collections.abc import Generator
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi.testclient import TestClient

from gateway.main import app
from gateway.models.notebooks import (
    BatchResult,
    BatchResultItem,
    NotebookAnalysis,
    NotebookInfo,
    NotebookReport,
    NotebookReportMetadata,
    NotebookReportOutputsSummary,
    NotebookSummary,
)

_VALID_UUID = "aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee"
_SECOND_UUID = "11111111-2222-3333-4444-555555555555"

_SAMPLE_NOTEBOOK_JSON = json.dumps({
    "cells": [{"cell_type": "code", "source": "import os", "outputs": [], "metadata": {}}],
    "metadata": {"kernelspec": {"name": "python3"}},
    "nbformat": 4,
    "nbformat_minor": 5,
})


def _make_notebook_info(
    notebook_id: str = _VALID_UUID,
    name: str = "Test Notebook",
    analyzed_at: float | None = None,
) -> NotebookInfo:
    return NotebookInfo(
        id=notebook_id,
        name=name,
        description="A test notebook",
        tags=["test"],
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
    store.count_search_notebooks = AsyncMock(return_value=0)
    store.get_notebook_analysis_json = AsyncMock(return_value=None)
    store.get_notebooks_summary = AsyncMock(return_value=NotebookSummary(
        total_notebooks=0,
        total_cells=0,
        total_code_cells=0,
        total_markdown_cells=0,
        total_code_lines=0,
        analyzed_count=0,
        pending_count=0,
        notebooks_with_errors=0,
        total_error_cells=0,
        top_imports=[],
    ))
    store.batch_get_notebook_ids = AsyncMock(return_value=[])
    store.batch_delete_notebooks = AsyncMock(return_value=[])
    return store


@pytest.fixture
def mock_store() -> MagicMock:
    return _make_mock_store()


@pytest.fixture
def notebook_client(mock_store: MagicMock) -> Generator[TestClient, None, None]:
    """TestClient with get_store overridden to return mock store.

    Does NOT use the context manager form to avoid triggering the app lifespan
    (which requires a live DATABASE_URL). Follows the pattern in test_api.py.
    """
    from gateway.api.deps import get_store
    from gateway.store import get_local_api_key

    async def _mock_get_store() -> MagicMock:
        return mock_store

    api_key = get_local_api_key()
    app.dependency_overrides[get_store] = _mock_get_store
    try:
        yield TestClient(app, headers={"Authorization": f"Bearer {api_key}"})
    finally:
        app.dependency_overrides.pop(get_store, None)



class TestNotebookList:
    def test_list_notebooks_empty(self, notebook_client: TestClient, mock_store: MagicMock) -> None:
        mock_store.list_notebooks.return_value = []
        mock_store.count_notebooks.return_value = 0
        response = notebook_client.get("/api/notebooks")
        assert response.status_code == 200
        data = response.json()
        assert data["items"] == []
        assert data["total"] == 0

    def test_list_notebooks_with_items(self, notebook_client: TestClient, mock_store: MagicMock) -> None:
        nb = _make_notebook_info()
        mock_store.list_notebooks.return_value = [nb]
        mock_store.count_notebooks.return_value = 1
        response = notebook_client.get("/api/notebooks")
        assert response.status_code == 200
        data = response.json()
        assert len(data["items"]) == 1
        assert data["items"][0]["name"] == "Test Notebook"
        assert data["total"] == 1

    def test_list_notebooks_invalid_sort_by(self, notebook_client: TestClient) -> None:
        response = notebook_client.get("/api/notebooks?sort_by=invalid")
        assert response.status_code == 400


class TestNotebookUpload:
    def test_upload_notebook_success(self, notebook_client: TestClient, mock_store: MagicMock) -> None:
        info = _make_notebook_info(analyzed_at=1_000_001.0)
        mock_store.create_notebook.return_value = info
        mock_store.update_notebook_analysis.return_value = True
        mock_store.get_notebook_meta.return_value = info

        with (
            patch("gateway.api.notebooks._save_notebook_file"),
            patch("gateway.api.notebooks._parse_notebook", return_value={
                "cell_count": 1,
                "code_cell_count": 1,
                "markdown_cell_count": 0,
                "kernel_name": "python3",
            }),
            patch("gateway.api.notebooks._analyze_notebook_content", return_value={
                "cell_counts": {"code": 1},
                "imports": ["os"],
                "execution_order_gaps": [],
                "error_cells": [],
                "output_summary": {},
                "total_code_lines": 1,
                "functions_defined": [],
                "kernel_info": None,
            }),
        ):
            response = notebook_client.post(
                "/api/notebooks",
                json={"name": "My Notebook", "content": _SAMPLE_NOTEBOOK_JSON},
            )
        assert response.status_code == 201
        data = response.json()
        assert data["name"] == "Test Notebook"

    def test_upload_invalid_json(self, notebook_client: TestClient) -> None:
        response = notebook_client.post(
            "/api/notebooks",
            json={"name": "Bad", "content": "not json"},
        )
        assert response.status_code == 422

    def test_upload_missing_cells(self, notebook_client: TestClient) -> None:
        response = notebook_client.post(
            "/api/notebooks",
            json={"name": "Bad", "content": '{"no_cells": true}'},
        )
        assert response.status_code == 422


class TestNotebookGet:
    def test_get_notebook_found(self, notebook_client: TestClient, mock_store: MagicMock) -> None:
        mock_store.get_notebook_meta.return_value = _make_notebook_info()
        response = notebook_client.get(f"/api/notebooks/{_VALID_UUID}")
        assert response.status_code == 200
        assert response.json()["name"] == "Test Notebook"

    def test_get_notebook_not_found(self, notebook_client: TestClient, mock_store: MagicMock) -> None:
        mock_store.get_notebook_meta.return_value = None
        response = notebook_client.get(f"/api/notebooks/{_VALID_UUID}")
        assert response.status_code == 404

    def test_get_notebook_invalid_uuid(self, notebook_client: TestClient) -> None:
        response = notebook_client.get("/api/notebooks/not-a-uuid")
        assert response.status_code == 422


class TestNotebookDelete:
    def test_delete_notebook_found(self, notebook_client: TestClient, mock_store: MagicMock) -> None:
        mock_store.get_notebook_meta.return_value = _make_notebook_info()
        mock_store.delete_notebook_meta.return_value = True
        mock_store.log_notebook_activity = AsyncMock()
        with patch("gateway.api.notebooks._delete_notebook_file"):
            response = notebook_client.delete(f"/api/notebooks/{_VALID_UUID}")
        assert response.status_code == 204

    def test_delete_notebook_not_found(self, notebook_client: TestClient, mock_store: MagicMock) -> None:
        mock_store.get_notebook_meta.return_value = None
        response = notebook_client.delete(f"/api/notebooks/{_VALID_UUID}")
        assert response.status_code == 404


class TestNotebookUpdate:
    def test_update_name(self, notebook_client: TestClient, mock_store: MagicMock) -> None:
        updated = _make_notebook_info(name="New Name")
        mock_store.update_notebook_metadata.return_value = updated
        response = notebook_client.patch(f"/api/notebooks/{_VALID_UUID}", json={"name": "New Name"})
        assert response.status_code == 200
        assert response.json()["name"] == "New Name"

    def test_update_no_fields(self, notebook_client: TestClient) -> None:
        response = notebook_client.patch(f"/api/notebooks/{_VALID_UUID}", json={})
        assert response.status_code == 400


class TestNotebookSearch:
    def test_search_success(self, notebook_client: TestClient, mock_store: MagicMock) -> None:
        nb = _make_notebook_info()
        mock_store.search_notebooks.return_value = [nb]
        mock_store.count_search_notebooks.return_value = 1
        response = notebook_client.get("/api/notebooks/search?q=test")
        assert response.status_code == 200
        data = response.json()
        assert len(data["items"]) == 1

    def test_search_empty_query(self, notebook_client: TestClient) -> None:
        response = notebook_client.get("/api/notebooks/search?q=")
        assert response.status_code == 400


class TestNotebookCompare:
    def test_compare_success(self, notebook_client: TestClient, mock_store: MagicMock) -> None:
        left_meta = _make_notebook_info(_VALID_UUID, "Left")
        right_meta = _make_notebook_info(_SECOND_UUID, "Right")
        mock_store.get_notebook_meta.side_effect = lambda nid: left_meta if nid == _VALID_UUID else right_meta
        mock_store.get_notebook_analysis_json.return_value = None

        nb_dict = json.loads(_SAMPLE_NOTEBOOK_JSON)
        with patch("gateway.api.notebooks._load_notebook_file", return_value=nb_dict):
            with patch("gateway.api.notebooks.build_notebook_comparison") as mock_cmp:
                from gateway.models.notebooks import ComparisonSummary, NotebookComparison
                mock_cmp.return_value = NotebookComparison(
                    left_notebook=left_meta,
                    right_notebook=right_meta,
                    analysis=None,
                    cell_diffs=[],
                    summary=ComparisonSummary(),
                )
                response = notebook_client.get(f"/api/notebooks/{_VALID_UUID}/compare/{_SECOND_UUID}")
        assert response.status_code == 200

    def test_compare_self(self, notebook_client: TestClient) -> None:
        response = notebook_client.get(f"/api/notebooks/{_VALID_UUID}/compare/{_VALID_UUID}")
        assert response.status_code == 400

    def test_compare_not_found(self, notebook_client: TestClient, mock_store: MagicMock) -> None:
        mock_store.get_notebook_meta.return_value = None
        response = notebook_client.get(f"/api/notebooks/{_VALID_UUID}/compare/{_SECOND_UUID}")
        assert response.status_code == 404


class TestNotebookDownload:
    def test_download_success(self, notebook_client: TestClient, mock_store: MagicMock) -> None:
        mock_store.get_notebook_meta.return_value = _make_notebook_info()
        with patch("gateway.api.notebooks._load_notebook_file_raw", return_value=_SAMPLE_NOTEBOOK_JSON):
            response = notebook_client.get(f"/api/notebooks/{_VALID_UUID}/download")
        assert response.status_code == 200
        assert "Content-Disposition" in response.headers
        assert "Test Notebook" in response.headers["Content-Disposition"]


class TestNotebookAnalyze:
    def test_analyze_success(self, notebook_client: TestClient, mock_store: MagicMock) -> None:
        mock_store.get_notebook_meta.return_value = _make_notebook_info()
        mock_store.update_notebook_analysis.return_value = True
        nb_dict = json.loads(_SAMPLE_NOTEBOOK_JSON)
        analysis_result = {
            "cell_counts": {"code": 1},
            "imports": ["os"],
            "execution_order_gaps": [],
            "error_cells": [],
            "output_summary": {},
            "total_code_lines": 1,
            "functions_defined": [],
            "kernel_info": None,
        }
        with (
            patch("gateway.api.notebooks._load_notebook_file", return_value=nb_dict),
            patch("gateway.api.notebooks._analyze_notebook_content", return_value=analysis_result),
        ):
            response = notebook_client.post(f"/api/notebooks/{_VALID_UUID}/analyze")
        assert response.status_code == 200
        data = response.json()
        assert data["notebook_id"] == _VALID_UUID

    def test_analyze_not_found(self, notebook_client: TestClient, mock_store: MagicMock) -> None:
        mock_store.get_notebook_meta.return_value = None
        response = notebook_client.post(f"/api/notebooks/{_VALID_UUID}/analyze")
        assert response.status_code == 404


class TestNotebookCells:
    def test_get_cells_success(self, notebook_client: TestClient, mock_store: MagicMock) -> None:
        mock_store.get_notebook_meta.return_value = _make_notebook_info()
        nb_dict = json.loads(_SAMPLE_NOTEBOOK_JSON)
        with patch("gateway.api.notebooks._load_notebook_file", return_value=nb_dict):
            response = notebook_client.get(f"/api/notebooks/{_VALID_UUID}/cells")
        assert response.status_code == 200
        data = response.json()
        assert isinstance(data, list)
        assert len(data) == 1
        assert data[0]["cell_type"] == "code"

    def test_get_cells_by_type(self, notebook_client: TestClient, mock_store: MagicMock) -> None:
        mock_store.get_notebook_meta.return_value = _make_notebook_info()
        nb_dict = {
            "cells": [
                {"cell_type": "code", "source": "x=1", "outputs": [], "metadata": {}},
                {"cell_type": "markdown", "source": "# Hi", "metadata": {}},
            ],
            "metadata": {},
            "nbformat": 4,
            "nbformat_minor": 5,
        }
        with patch("gateway.api.notebooks._load_notebook_file", return_value=nb_dict):
            response = notebook_client.get(f"/api/notebooks/{_VALID_UUID}/cells?cell_type=code")
        assert response.status_code == 200
        data = response.json()
        assert all(c["cell_type"] == "code" for c in data)

    def test_get_cells_not_found(self, notebook_client: TestClient, mock_store: MagicMock) -> None:
        mock_store.get_notebook_meta.return_value = None
        response = notebook_client.get(f"/api/notebooks/{_VALID_UUID}/cells")
        assert response.status_code == 404


class TestNotebookReport:
    def test_get_report_success(self, notebook_client: TestClient, mock_store: MagicMock) -> None:
        info = _make_notebook_info(analyzed_at=1_000_001.0)
        mock_store.get_notebook_meta.return_value = info
        mock_store.get_notebook_analysis_json.return_value = None
        nb_dict = json.loads(_SAMPLE_NOTEBOOK_JSON)
        with patch("gateway.api.notebooks._load_notebook_file", return_value=nb_dict):
            response = notebook_client.get(f"/api/notebooks/{_VALID_UUID}/report")
        assert response.status_code == 200
        data = response.json()
        assert data["report_version"] == "1.0"
        assert data["notebook"]["id"] == _VALID_UUID

    def test_get_report_not_found(self, notebook_client: TestClient, mock_store: MagicMock) -> None:
        mock_store.get_notebook_meta.return_value = None
        response = notebook_client.get(f"/api/notebooks/{_VALID_UUID}/report")
        assert response.status_code == 404
