"""Tests for the GET /api/notebook/static endpoint.

These are unit tests that exercise _build_static_payload,
_resolve_and_validate, and _validate_session_shape directly, without
needing the full Starlette app stack.  The schema-shape contract test
(test 6) asserts that the JSON produced by the endpoint matches what
mount.tsx's mountOptionsSchema accepts.
"""

from __future__ import annotations

import json
import textwrap
from typing import TYPE_CHECKING

import pytest

from signalpilot._server.api.endpoints.notebook_static import (
    _build_static_payload,
    _resolve_and_validate,
    _validate_session_shape,
)

if TYPE_CHECKING:
    from pathlib import Path

# ---------------------------------------------------------------------------
# Minimal valid SignalPilot notebook file content
# ---------------------------------------------------------------------------

_NOTEBOOK_CONTENT = textwrap.dedent(
    """\
    import signalpilot as sp

    __generated_with = "0.1.0"
    app = sp.App()


    @app.cell
    def __():
        x = 1
        return (x,)
    """
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _write_notebook(tmp_path: Path, filename: str = "notebook.py") -> Path:
    """Write a minimal valid notebook file and return its Path."""
    nb = tmp_path / filename
    nb.write_text(_NOTEBOOK_CONTENT, encoding="utf-8")
    return nb


def _write_valid_session(notebook_path: Path) -> Path:
    """Write a valid (non-stale) session cache JSON for a notebook.

    Builds cells with code_hash values that match the notebook's actual
    cell content so the staleness check passes.  The session_view state
    (outputs, console) is intentionally empty — the point is to produce a
    structurally valid, non-stale snapshot, not to replay real outputs.
    """
    from signalpilot._session.notebook import load_notebook
    from signalpilot._session.state.serialize import get_session_cache_file
    from signalpilot._utils.code import hash_code
    from signalpilot._utils.paths import maybe_make_dirs

    fm = load_notebook(str(notebook_path))
    cell_manager = fm.app.cell_manager
    cells: list[dict[str, object]] = []
    for cell_id in cell_manager.cell_ids():
        code = cell_manager.get_cell_code(cell_id) or ""
        code_hash = hash_code(code) if code else None
        cells.append(
            {
                "id": str(cell_id),
                "code_hash": code_hash,
                "outputs": [],
                "console": [],
            }
        )

    session_json = {
        "version": "1",
        "metadata": {
            "signalpilot_version": None,
            "script_metadata_hash": None,
        },
        "cells": cells,
    }

    cache_path = get_session_cache_file(notebook_path)
    maybe_make_dirs(cache_path)
    cache_path.write_text(json.dumps(session_json, indent=2), encoding="utf-8")
    return cache_path


# ---------------------------------------------------------------------------
# Test 1: happy path — session JSON present
# ---------------------------------------------------------------------------


def test_happy_path_with_session(tmp_path: Path) -> None:
    """Endpoint returns {code, session, notebook, filename} with a fresh session."""
    nb = _write_notebook(tmp_path)
    _write_valid_session(nb)

    result = _build_static_payload(nb, str(tmp_path))

    assert set(result.keys()) == {"code", "session", "notebook", "filename"}
    assert result["code"] == _NOTEBOOK_CONTENT
    # filename must be relative to the workspace directory, not absolute
    assert result["filename"] == "notebook.py"
    assert result["session"] is not None
    assert result["session"]["version"] == "1"
    assert isinstance(result["notebook"], dict)
    assert result["notebook"]["version"] == "1"


# ---------------------------------------------------------------------------
# Test 2: session JSON missing
# ---------------------------------------------------------------------------


def test_missing_session_returns_none(tmp_path: Path) -> None:
    """When no cache file exists, session is None; notebook is still present."""
    nb = _write_notebook(tmp_path)
    # No session cache written.

    result = _build_static_payload(nb, str(tmp_path))

    assert result["session"] is None
    assert result["notebook"]["version"] == "1"
    assert isinstance(result["notebook"]["cells"], list)


# ---------------------------------------------------------------------------
# Test 3: session JSON stale (cell hash mismatch)
# ---------------------------------------------------------------------------


def test_stale_session_returns_none(tmp_path: Path) -> None:
    """A session whose code_hash doesn't match the current cells is treated as None."""
    nb = _write_notebook(tmp_path)

    # Write a valid session first, then modify the notebook so hashes diverge.
    _write_valid_session(nb)

    # Replace the cell body with different code to create a code_hash mismatch.
    # Comments outside @app.cell are ignored by the parser, so we must change
    # the cell body itself.
    nb.write_text(
        _NOTEBOOK_CONTENT.replace("x = 1", "x = 999  # mutated"),
        encoding="utf-8",
    )

    result = _build_static_payload(nb, str(tmp_path))
    assert result["session"] is None


# ---------------------------------------------------------------------------
# Test 4: 404 on missing file
# ---------------------------------------------------------------------------


def test_missing_file_raises_404(tmp_path: Path) -> None:
    """When the file does not exist, _build_static_payload raises FileNotFoundError."""
    missing = tmp_path / "ghost.py"
    with pytest.raises(FileNotFoundError):
        _build_static_payload(missing, str(tmp_path))


# ---------------------------------------------------------------------------
# Test 5: 400 on path traversal
# ---------------------------------------------------------------------------


def test_path_traversal_rejected(tmp_path: Path) -> None:
    """_resolve_and_validate raises HTTPException(403) on path traversal."""
    from starlette.exceptions import HTTPException as StarletteHTTPException

    from signalpilot._utils.http import HTTPException as SpHTTPException

    # tmp_path acts as the "workspace directory". The traversal tries to
    # escape it via "..".
    with pytest.raises((SpHTTPException, StarletteHTTPException)) as exc_info:
        _resolve_and_validate("../../etc/passwd", str(tmp_path))

    assert getattr(exc_info.value, "status_code", None) in (400, 403)


# ---------------------------------------------------------------------------
# Test 5b: 400 when directory is None
# ---------------------------------------------------------------------------


def test_no_directory_raises_400() -> None:
    """_resolve_and_validate raises HTTPException(400) when directory is None."""
    from starlette.exceptions import HTTPException as StarletteHTTPException

    from signalpilot._utils.http import HTTPException as SpHTTPException

    with pytest.raises((SpHTTPException, StarletteHTTPException)) as exc_info:
        _resolve_and_validate("notebook.py", None)

    assert getattr(exc_info.value, "status_code", None) == 400


# ---------------------------------------------------------------------------
# Test 5c: should_send_code_to_frontend gate — 403 in RUN mode
# ---------------------------------------------------------------------------


def test_should_send_code_gate_denies_run_mode(tmp_path: Path) -> None:
    """get_notebook_static returns 403 when should_send_code_to_frontend() is False."""
    from unittest.mock import MagicMock, patch

    import starlette.testclient
    from starlette.applications import Starlette
    from starlette.authentication import (
        AuthCredentials,
        AuthenticationBackend,
        BaseUser,
        SimpleUser,
    )
    from starlette.middleware.authentication import AuthenticationMiddleware
    from starlette.routing import Mount

    from signalpilot._server.api.endpoints import notebook_static

    class AllowAllBackend(AuthenticationBackend):
        async def authenticate(  # type: ignore[override]
            self, *_args: object
        ) -> tuple[AuthCredentials, BaseUser] | None:
            return AuthCredentials(["read"]), SimpleUser("test-user")

    mock_session_manager = MagicMock()
    mock_session_manager.should_send_code_to_frontend.return_value = False
    mock_session_manager.workspace.directory = str(tmp_path)

    mock_app_state = MagicMock()
    mock_app_state.session_manager = mock_session_manager

    nb = _write_notebook(tmp_path)

    with patch.object(notebook_static, "AppState", return_value=mock_app_state):
        app = Starlette(routes=[Mount("/notebook", app=notebook_static.router)])
        app.add_middleware(AuthenticationMiddleware, backend=AllowAllBackend())
        client = starlette.testclient.TestClient(app, raise_server_exceptions=False)
        resp = client.get(f"/notebook/static?file={nb.name}")

    assert resp.status_code == 403


# ---------------------------------------------------------------------------
# Test 5d: _validate_session_shape
# ---------------------------------------------------------------------------


def test_validate_session_shape_accepts_valid() -> None:
    """_validate_session_shape returns True for a well-formed session dict."""
    valid = {"version": "1", "metadata": {}, "cells": []}
    assert _validate_session_shape(valid) is True


def test_validate_session_shape_rejects_missing_key() -> None:
    """_validate_session_shape returns False when a required key is absent."""
    missing_cells = {"version": "1", "metadata": {}}
    assert _validate_session_shape(missing_cells) is False


def test_validate_session_shape_rejects_non_dict() -> None:
    """_validate_session_shape returns False for non-dict inputs."""
    assert _validate_session_shape([]) is False
    assert _validate_session_shape("string") is False
    assert _validate_session_shape(None) is False


def test_malformed_session_cache_returns_none(tmp_path: Path) -> None:
    """A session cache missing required keys is treated as None."""
    nb = _write_notebook(tmp_path)

    # Write a cache file that is valid JSON but lacks required keys.
    from signalpilot._session.state.serialize import get_session_cache_file
    from signalpilot._utils.paths import maybe_make_dirs

    cache_path = get_session_cache_file(nb)
    maybe_make_dirs(cache_path)
    # Missing "cells" key — structurally invalid session.
    cache_path.write_text(
        json.dumps({"version": "1", "metadata": {}}), encoding="utf-8"
    )

    result = _build_static_payload(nb, str(tmp_path))
    assert result["session"] is None


# ---------------------------------------------------------------------------
# Test 6: schema-shape contract — matches mountOptionsSchema
# ---------------------------------------------------------------------------


def _assert_notebook_schema(notebook: dict) -> None:  # type: ignore[type-arg]
    """Assert notebook matches mountOptionsSchema.notebook (mount.tsx:313-322).

    version: z.literal("1")
    metadata: z.any()          (must be present and be a dict)
    cells: z.array(z.any())    (must be a list)
    """
    assert notebook["version"] == "1", (
        f"notebook.version must be literal '1', got {notebook['version']!r}"
    )
    assert isinstance(notebook.get("metadata"), dict), (
        "notebook.metadata must be a dict"
    )
    assert isinstance(notebook.get("cells"), list), (
        "notebook.cells must be a list"
    )


def _assert_session_schema(session: dict) -> None:  # type: ignore[type-arg]
    """Assert session matches mountOptionsSchema.session (mount.tsx:298-308).

    version: z.literal("1")
    metadata: z.any()
    cells: z.array(z.any())
    """
    assert session["version"] == "1", (
        f"session.version must be literal '1', got {session['version']!r}"
    )
    assert isinstance(session.get("metadata"), dict), (
        "session.metadata must be a dict"
    )
    assert isinstance(session.get("cells"), list), (
        "session.cells must be a list"
    )


def test_schema_shape_contract(tmp_path: Path) -> None:
    """Schema-shape contract: endpoint output satisfies mountOptionsSchema.

    This test catches drift if serialize_session_view or serialize_notebook
    ever changes its version literal or drops required top-level keys.
    It mirrors the structural rules of the zod schema at mount.tsx:298-322.
    """
    nb = _write_notebook(tmp_path)
    _write_valid_session(nb)

    result = _build_static_payload(nb, str(tmp_path))

    # Round-trip through JSON serialization to ensure the payload is
    # serializable (i.e. contains no non-JSON types like dataclasses).
    serialized = json.dumps(result)
    payload = json.loads(serialized)

    # --- notebook shape ---
    notebook = payload["notebook"]
    _assert_notebook_schema(notebook)
    # Each cell must be a dict with expected keys.
    for cell in notebook["cells"]:
        assert isinstance(cell, dict), "notebook.cells[i] must be a dict"
        assert "id" in cell, "notebook.cells[i] must have 'id'"
        assert "code" in cell, "notebook.cells[i] must have 'code'"

    # --- session shape (when present) ---
    session = payload["session"]
    assert session is not None, (
        "session should not be None — a valid cache was written"
    )
    _assert_session_schema(session)
    for cell in session["cells"]:
        assert isinstance(cell, dict), "session.cells[i] must be a dict"
