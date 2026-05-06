"""Tests for pure functions in gateway/store/notebook_files.py.

No DB mocking needed — all functions under test are pure or file-only.
"""

from __future__ import annotations

from unittest.mock import patch

import pytest

from gateway.models.notebooks import NotebookInfo
from gateway.store.notebook_files import (
    _analyze_notebook_content,
    _build_report_data,
    _cell_source,
    _parse_notebook,
    _safe_notebook_path,
    build_notebook_comparison,
)

_VALID_UUID = "aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee"
_SECOND_UUID = "11111111-2222-3333-4444-555555555555"


def _make_code_cell(source: str | list[str], outputs: list[dict] | None = None, execution_count: int | None = None) -> dict:
    return {
        "cell_type": "code",
        "source": source,
        "outputs": outputs or [],
        "execution_count": execution_count,
        "metadata": {},
    }


def _make_markdown_cell(source: str) -> dict:
    return {"cell_type": "markdown", "source": source, "metadata": {}}


def _make_notebook_info(notebook_id: str, name: str = "Test Notebook") -> NotebookInfo:
    return NotebookInfo(
        id=notebook_id,
        name=name,
        description="",
        tags=[],
        cell_count=1,
        code_cell_count=1,
        markdown_cell_count=0,
        kernel_name="python3",
        created_at=0.0,
        updated_at=0.0,
        analyzed_at=None,
    )


class TestParseNotebook:
    def test_parse_simple_notebook(self) -> None:
        nb = {
            "cells": [
                _make_code_cell("x = 1"),
                _make_markdown_cell("# Title"),
                _make_code_cell("y = 2"),
            ],
            "metadata": {"kernelspec": {"name": "python3"}},
        }
        result = _parse_notebook(nb)
        assert result["cell_count"] == 3
        assert result["code_cell_count"] == 2
        assert result["markdown_cell_count"] == 1
        assert result["kernel_name"] == "python3"

    def test_parse_empty_notebook(self) -> None:
        nb: dict = {"metadata": {}}
        result = _parse_notebook(nb)
        assert result["cell_count"] == 0
        assert result["code_cell_count"] == 0
        assert result["markdown_cell_count"] == 0

    def test_parse_kernel_name_extraction(self) -> None:
        nb = {
            "cells": [],
            "metadata": {"kernelspec": {"name": "ir"}},
        }
        result = _parse_notebook(nb)
        assert result["kernel_name"] == "ir"


class TestAnalyzeNotebookContent:
    def test_analyze_imports(self) -> None:
        nb = {
            "cells": [
                _make_code_cell("import numpy\nfrom pandas import DataFrame"),
            ]
        }
        result = _analyze_notebook_content(nb)
        assert "numpy" in result["imports"]
        assert "pandas" in result["imports"]
        # No duplicates
        assert len([i for i in result["imports"] if i == "numpy"]) == 1

    def test_analyze_functions(self) -> None:
        nb = {
            "cells": [
                _make_code_cell("def foo():\n    pass\ndef bar():\n    pass"),
            ]
        }
        result = _analyze_notebook_content(nb)
        assert "foo" in result["functions_defined"]
        assert "bar" in result["functions_defined"]

    def test_analyze_error_cells(self) -> None:
        error_output = {"output_type": "error", "ename": "ValueError", "evalue": "bad", "traceback": []}
        nb = {
            "cells": [
                _make_code_cell("x = 1", outputs=[error_output, error_output]),
            ]
        }
        result = _analyze_notebook_content(nb)
        # Cell index 0 has errors; deduplication means only one entry
        assert 0 in result["error_cells"]
        assert result["error_cells"].count(0) == 1

    def test_analyze_code_lines(self) -> None:
        nb = {
            "cells": [
                _make_code_cell("a = 1\nb = 2\nc = 3"),
                _make_code_cell("d = 4\ne = 5"),
            ]
        }
        result = _analyze_notebook_content(nb)
        assert result["total_code_lines"] == 5

    def test_analyze_execution_gaps(self) -> None:
        nb = {
            "cells": [
                _make_code_cell("", execution_count=1),
                _make_code_cell("", execution_count=3),
                _make_code_cell("", execution_count=5),
            ]
        }
        result = _analyze_notebook_content(nb)
        assert 2 in result["execution_order_gaps"]
        assert 4 in result["execution_order_gaps"]

    def test_analyze_output_summary(self) -> None:
        stream_output = {"output_type": "stream", "name": "stdout", "text": "hello"}
        execute_output = {"output_type": "execute_result", "data": {"text/plain": "42"}, "metadata": {}, "execution_count": 1}
        nb = {
            "cells": [
                _make_code_cell("print('hello')", outputs=[stream_output, execute_output]),
            ]
        }
        result = _analyze_notebook_content(nb)
        assert result["output_summary"].get("stream", 0) >= 1
        assert result["output_summary"].get("execute_result", 0) >= 1

    def test_analyze_cell_source_list_format(self) -> None:
        nb = {
            "cells": [
                _make_code_cell(["import os\n", "import sys\n"]),
            ]
        }
        result = _analyze_notebook_content(nb)
        assert "os" in result["imports"]
        assert "sys" in result["imports"]

    def test_cell_source_string_format(self) -> None:
        cell = {"source": "import math", "cell_type": "code"}
        assert _cell_source(cell) == "import math"

    def test_cell_source_list_format(self) -> None:
        cell = {"source": ["import math\n", "import os"], "cell_type": "code"}
        assert _cell_source(cell) == "import math\nimport os"


class TestBuildReportData:
    def test_report_data_basic(self) -> None:
        nb_content = {
            "cells": [
                _make_code_cell("x = 1", outputs=[{"output_type": "execute_result", "data": {}, "metadata": {}, "execution_count": 1}]),
                _make_markdown_cell("# Header"),
            ],
            "metadata": {"kernelspec": {"name": "python3"}},
            "nbformat": 4,
            "nbformat_minor": 5,
        }
        result = _build_report_data(analysis_json=None, nb_content=nb_content)
        assert len(result["cell_details"]) == 2
        assert result["outputs_summary"]["total_outputs"] == 1
        assert result["metadata"]["nbformat"] == 4

    def test_report_data_caps_at_50_cells(self) -> None:
        cells = [_make_code_cell(f"x = {i}", outputs=[{"output_type": "stream", "name": "stdout", "text": f"{i}"}]) for i in range(60)]
        nb_content = {"cells": cells, "metadata": {}, "nbformat": 4, "nbformat_minor": 5}
        result = _build_report_data(analysis_json=None, nb_content=nb_content)
        # cell_details capped at 50
        assert len(result["cell_details"]) == 50
        # but total_outputs counts all 60 cells
        assert result["outputs_summary"]["total_outputs"] == 60


class TestBuildNotebookComparison:
    def _make_nb(self, cells: list[dict]) -> dict:
        return {"cells": cells, "metadata": {}}

    def test_comparison_identical_notebooks(self) -> None:
        cell = _make_code_cell("x = 1")
        left_nb = self._make_nb([cell])
        right_nb = self._make_nb([cell])
        left_meta = _make_notebook_info(_VALID_UUID, "Left")
        right_meta = _make_notebook_info(_SECOND_UUID, "Right")
        result = build_notebook_comparison(left_meta, right_meta, left_nb, right_nb, None, None)
        assert all(d.status == "unchanged" for d in result.cell_diffs)
        assert result.summary.modified == 0

    def test_comparison_added_cells(self) -> None:
        cell = _make_code_cell("x = 1")
        left_nb = self._make_nb([cell])
        right_nb = self._make_nb([cell, _make_code_cell("y = 2")])
        left_meta = _make_notebook_info(_VALID_UUID, "Left")
        right_meta = _make_notebook_info(_SECOND_UUID, "Right")
        result = build_notebook_comparison(left_meta, right_meta, left_nb, right_nb, None, None)
        assert any(d.status == "added" for d in result.cell_diffs)
        assert result.summary.added == 1

    def test_comparison_removed_cells(self) -> None:
        cell = _make_code_cell("x = 1")
        left_nb = self._make_nb([cell, _make_code_cell("z = 3")])
        right_nb = self._make_nb([cell])
        left_meta = _make_notebook_info(_VALID_UUID, "Left")
        right_meta = _make_notebook_info(_SECOND_UUID, "Right")
        result = build_notebook_comparison(left_meta, right_meta, left_nb, right_nb, None, None)
        assert any(d.status == "removed" for d in result.cell_diffs)
        assert result.summary.removed == 1

    def test_comparison_modified_cells(self) -> None:
        left_nb = self._make_nb([_make_code_cell("x = 1")])
        right_nb = self._make_nb([_make_code_cell("x = 999")])
        left_meta = _make_notebook_info(_VALID_UUID, "Left")
        right_meta = _make_notebook_info(_SECOND_UUID, "Right")
        result = build_notebook_comparison(left_meta, right_meta, left_nb, right_nb, None, None)
        assert result.cell_diffs[0].status == "modified"
        assert result.summary.modified == 1

    def test_comparison_analysis_diff(self) -> None:
        cell = _make_code_cell("x = 1")
        nb = self._make_nb([cell])
        left_meta = _make_notebook_info(_VALID_UUID, "Left")
        right_meta = _make_notebook_info(_SECOND_UUID, "Right")
        left_analysis = {"imports": ["numpy"], "functions_defined": [], "error_cells": [], "total_code_lines": 1}
        right_analysis = {"imports": ["numpy", "pandas"], "functions_defined": [], "error_cells": [], "total_code_lines": 2}
        result = build_notebook_comparison(left_meta, right_meta, nb, nb, left_analysis, right_analysis)
        assert result.analysis is not None
        assert "pandas" in result.analysis.added_imports
        assert result.analysis.removed_imports == []

    def test_comparison_no_analysis(self) -> None:
        cell = _make_code_cell("x = 1")
        nb = self._make_nb([cell])
        left_meta = _make_notebook_info(_VALID_UUID, "Left")
        right_meta = _make_notebook_info(_SECOND_UUID, "Right")
        result = build_notebook_comparison(left_meta, right_meta, nb, nb, None, None)
        assert result.analysis is None


class TestSafeNotebookPath:
    def test_valid_uuid_accepted(self, tmp_path) -> None:
        with patch("gateway.store.notebook_files._notebooks_dir", return_value=tmp_path):
            path = _safe_notebook_path(_VALID_UUID)
        assert str(path).endswith(f"{_VALID_UUID}.ipynb")

    def test_invalid_id_rejected(self, tmp_path) -> None:
        with patch("gateway.store.notebook_files._notebooks_dir", return_value=tmp_path):
            with pytest.raises(ValueError):
                _safe_notebook_path("../../etc/passwd")

    def test_non_uuid_rejected(self, tmp_path) -> None:
        with patch("gateway.store.notebook_files._notebooks_dir", return_value=tmp_path):
            with pytest.raises(ValueError):
                _safe_notebook_path("not-a-uuid")
