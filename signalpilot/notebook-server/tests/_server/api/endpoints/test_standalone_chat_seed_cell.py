"""The seeded chat notebook defines pd and np in a registered cell."""

from __future__ import annotations

import json
from typing import TYPE_CHECKING

import pytest

from signalpilot._ast.load import load_app
from signalpilot._server.ai.notebook_mcp import (
    NotebookToolError,
    _validate_candidate_graph,
)
from signalpilot._server.api.endpoints import (
    standalone_chat_runtime as chat_runtime,
)
from signalpilot._types.ids import CellId_t

if TYPE_CHECKING:
    from pathlib import Path


def _seed(tmp_path: Path) -> Path:
    return chat_runtime._seed_notebook_file(
        scratch=tmp_path,
        name="analysis",
        run_id="run-a",
        project_id="project-a",
        connection_name="warehouse-a",
        gateway_url="http://gateway:3300",
    )


def _seeded_cells(tmp_path: Path) -> list[tuple[CellId_t, str]]:
    app = load_app(_seed(tmp_path))
    assert app is not None
    return [
        (CellId_t(str(cd.cell_id)), cd.code)
        for cd in app._cell_manager.cell_data()
    ]


def test_setup_cell_imports_pandas_and_numpy(tmp_path: Path) -> None:
    assert "return db, np, pd" in _seed(tmp_path).read_text(encoding="utf-8")
    cells = _seeded_cells(tmp_path)
    setup = next(code for _id, code in cells if "sp.connect(" in code)
    assert "import pandas as pd" in setup
    assert "import numpy as np" in setup
    _validate_candidate_graph(cells)


def test_user_cell_reimporting_pandas_is_rejected_with_a_hint(
    tmp_path: Path,
) -> None:
    cells = _seeded_cells(tmp_path)
    setup_id = next(str(_id) for _id, code in cells if "sp.connect(" in code)
    new_id = CellId_t("deadbeef")

    with pytest.raises(NotebookToolError) as raised:
        _validate_candidate_graph(
            [*cells, (new_id, "import pandas as pd\ndf = pd.DataFrame()")],
            batch_cell_ids={str(new_id)},
            new_cell_ids={str(new_id)},
        )

    error = json.loads(str(raised.value))["error"]
    assert error["type"] == "MultipleDefinitionError"
    assert error["variable"] == "pd"
    assert error["hint"] == (
        f"cell {setup_id} already defines `pd`. Either include update_cell "
        f"for {setup_id} in this batch, or use a different name in the new cell."
    )
