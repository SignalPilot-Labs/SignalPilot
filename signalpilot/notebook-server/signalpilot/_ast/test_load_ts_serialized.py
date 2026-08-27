"""Loader tolerance for TS-serialized notebooks.

The browser-side serializer (signalpilot/web/notebook/core/notebook-file/
serialize.ts) is a best-effort port of codegen.py: cell signatures carry NO
refs (``def _():``), the trailing return is always a bare ``return``, and
``__generated_with`` holds a placeholder version. These tests pin down that
the Python loader accepts that output even when cells reference each other's
variables — refs/defs are recomputed from the AST at load time, so
signatures and return tuples are cosmetic.

If any of these tests start failing, the TS serializer's minimal-signature
assumption is broken and serialize.ts must be adjusted.
"""

from __future__ import annotations

import textwrap
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from pathlib import Path

from signalpilot._ast.load import get_notebook_status, load_app

# Exactly the shape serialize.ts emits: empty signatures and bare returns,
# despite `compute` depending on x/y from the first cell and the last cell
# depending on z and the top-level function.
_TS_STYLE_NOTEBOOK = textwrap.dedent(
    '''\
    import signalpilot as sp

    __generated_with = "0.1.0"
    app = sp.App()

    with app.setup:
        import math


    @app.cell
    def _():
        x = 1
        y = x + 1
        return


    @app.cell(hide_code=True)
    def compute():
        z = x + y + math.tau
        return


    @app.function
    def add(a, b):
        return a + b


    @app.cell
    def _():
        total = add(z, 1)
        print(total)
        return


    if __name__ == "__main__":
        app.run()
    '''
)

_EXPECTED_CODES = {
    "setup": "import math",
    "_0": "x = 1\ny = x + 1",
    "compute": "z = x + y + math.tau",
    "*add": "def add(a, b):\n    return a + b",
    "_1": "total = add(z, 1)\nprint(total)",
}

# serialize.ts::emptyNotebookPy() — the canonical new-notebook template.
_TS_EMPTY_NOTEBOOK = textwrap.dedent(
    '''\
    import signalpilot as sp

    __generated_with = "0.1.0"
    app = sp.App()


    @app.cell
    def _():
        return


    if __name__ == "__main__":
        app.run()
    '''
)


def _write(tmp_path: Path, contents: str) -> Path:
    nb = tmp_path / "notebook.py"
    nb.write_text(contents, encoding="utf-8")
    return nb


def test_ts_serialized_notebook_loads(tmp_path: Path) -> None:
    nb = _write(tmp_path, _TS_STYLE_NOTEBOOK)
    result = get_notebook_status(str(nb))
    # Empty signatures / bare returns must not be treated as data-loss
    # ("has_errors") or rejected ("invalid").
    assert result.status in ("valid", "has_warnings"), result.status
    assert result.notebook is not None

    app = load_app(str(nb))
    assert app is not None

    cell_data = list(app._cell_manager.cell_data())
    assert len(cell_data) == len(_EXPECTED_CODES)

    anon = 0
    for data in cell_data:
        name = data.name
        if name == "_":
            name = f"_{anon}"
            anon += 1
        assert name in _EXPECTED_CODES, name
        assert data.code == _EXPECTED_CODES[name]

    # Refs are recomputed from the AST even though the TS serializer wrote
    # empty signatures: `compute` must depend on x and y.
    compute = app._cell_manager.get_cell_data_by_name("compute")
    assert compute is not None and compute.cell is not None
    assert {"x", "y"} <= set(compute.cell._cell.refs)
    assert compute.config.hide_code is True


def test_ts_serialized_notebook_roundtrips_through_python_save(
    tmp_path: Path,
) -> None:
    """Re-serializing with the real codegen must preserve every cell code."""
    nb = _write(tmp_path, _TS_STYLE_NOTEBOOK)
    app = load_app(str(nb))
    assert app is not None
    from signalpilot._ast.app import InternalApp
    from signalpilot._ast.codegen import generate_filecontents_from_ir

    contents = generate_filecontents_from_ir(InternalApp(app).to_ir())
    # The python serializer now writes full signatures/returns, but the cell
    # codes themselves must be unchanged.
    resaved = tmp_path / "resaved.py"
    resaved.write_text(contents, encoding="utf-8")
    app2 = load_app(str(resaved))
    assert app2 is not None
    codes = [d.code for d in app._cell_manager.cell_data()]
    codes2 = [d.code for d in app2._cell_manager.cell_data()]
    assert codes == codes2


def test_ts_empty_notebook_template_loads(tmp_path: Path) -> None:
    nb = _write(tmp_path, _TS_EMPTY_NOTEBOOK)
    result = get_notebook_status(str(nb))
    assert result.status in ("valid", "has_warnings"), result.status

    app = load_app(str(nb))
    assert app is not None
    cell_data = list(app._cell_manager.cell_data())
    assert len(cell_data) == 1
    assert cell_data[0].code == ""
    assert cell_data[0].name == "_"
