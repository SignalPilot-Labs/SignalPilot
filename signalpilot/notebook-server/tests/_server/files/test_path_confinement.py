"""``path_confinement`` must keep caller-supplied paths inside the workspace.

Covers the four escape shapes an attacker actually has: an absolute path to
somewhere else, ``..`` traversal, a symlink planted inside the workspace that
points out of it, and a sibling directory that merely shares the root's name
prefix (``/workspace-evil``) -- the last of which passes any ``startswith``
containment check.

Runs anywhere the package imports -- no server, no event loop.
"""

from __future__ import annotations

import os
from pathlib import Path

import pytest

pc = pytest.importorskip("signalpilot._server.files.path_confinement")

from signalpilot._utils.http import HTTPException  # noqa: E402


@pytest.fixture()
def workspace(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """A confined workspace root with a sibling and an outside directory."""
    root = tmp_path / "workspace"
    (root / "nested" / "project").mkdir(parents=True)
    (tmp_path / "workspace-evil").mkdir()
    (tmp_path / "outside-workspace").mkdir()

    monkeypatch.setenv(pc.WORKSPACE_ROOT_ENV, str(root))
    # cwd is always an allowed root (the sandbox boot command chdirs into the
    # workspace), so point it at the workspace to keep the roots minimal.
    monkeypatch.chdir(root)
    return root


def _escapes(tmp_path: Path, root: Path) -> dict[str, str]:
    """Rejection cases, keyed by the shape of the escape."""
    cases = {
        "absolute_posix": "/tmp/outside-workspace",
        "absolute_sibling_of_root": str(tmp_path / "outside-workspace"),
        "sibling_prefix": str(root) + "-evil",
        "sibling_prefix_child": str(root) + "-evil/models",
        "dotdot_relative": "../../etc",
        "dotdot_embedded": "workspace/../../etc",
        "dotdot_absolute": str(root / ".." / ".." / "etc"),
        "nul_byte": "nested\x00/etc/passwd",
        "empty": "   ",
    }
    if os.name == "nt":
        cases["absolute_windows"] = "C:\\Windows\\Temp"
    else:
        cases["absolute_etc"] = "/etc/passwd"
    return cases


@pytest.mark.parametrize(
    "shape", sorted(_escapes(Path("/t"), Path("/t/workspace")))
)
def test_confine_rejects_escape(
    shape: str, workspace: Path, tmp_path: Path
) -> None:
    candidate = _escapes(tmp_path, workspace)[shape]

    with pytest.raises(HTTPException) as excinfo:
        pc.confine(candidate)

    assert excinfo.value.status_code == 400, shape


@pytest.mark.parametrize(
    "shape", sorted(_escapes(Path("/t"), Path("/t/workspace")))
)
def test_is_confined_is_false_not_raising(
    shape: str, workspace: Path, tmp_path: Path
) -> None:
    assert pc.is_confined(_escapes(tmp_path, workspace)[shape]) is False


def test_confine_rejects_symlink_escape(
    workspace: Path, tmp_path: Path
) -> None:
    """A symlink *inside* the workspace pointing out of it must be refused.

    Only the resolved target reveals this; the link's own path is a perfectly
    ordinary child of the root.
    """
    outside = tmp_path / "outside-workspace"
    link = workspace / "escape-link"
    try:
        link.symlink_to(outside, target_is_directory=True)
    except (OSError, NotImplementedError) as exc:
        pytest.skip(f"cannot create symlinks in this environment: {exc}")

    # Sanity: the unresolved link really does look like a workspace child.
    assert link.parent == workspace

    for candidate in (str(link), "escape-link", str(link / "models")):
        with pytest.raises(HTTPException) as excinfo:
            pc.confine(candidate)
        assert excinfo.value.status_code == 400, candidate


@pytest.mark.parametrize(
    "candidate",
    [
        "nested",
        "nested/project",
        "does/not/exist/yet",
        ".",
    ],
)
def test_confine_accepts_relative_in_workspace(
    candidate: str, workspace: Path
) -> None:
    resolved = pc.confine(candidate)

    assert resolved.is_relative_to(workspace.resolve())


def test_confine_accepts_root_itself(workspace: Path) -> None:
    assert pc.confine(str(workspace)) == workspace.resolve()


def test_confine_accepts_nested_absolute(workspace: Path) -> None:
    nested = workspace / "nested" / "project"

    assert pc.confine(str(nested)) == nested.resolve()


def test_confine_accepts_interior_dot_segments(workspace: Path) -> None:
    """``.`` segments are normalised, not treated as traversal."""
    assert pc.confine("./nested/./project") == (
        workspace / "nested" / "project"
    ).resolve()


def test_relative_paths_resolve_against_root_not_cwd(
    workspace: Path, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """A relative path must not be read against an unrelated cwd."""
    elsewhere = tmp_path / "elsewhere"
    elsewhere.mkdir()
    monkeypatch.chdir(elsewhere)

    assert pc.confine("nested") == (workspace / "nested").resolve()


def test_confine_optional_passes_through_empty(workspace: Path) -> None:
    assert pc.confine_optional(None) is None
    assert pc.confine_optional("") is None
    assert pc.confine_optional("   ") is None
    assert pc.confine_optional("nested") == (workspace / "nested").resolve()


def test_workspace_roots_prefers_configured_root(workspace: Path) -> None:
    assert pc.workspace_roots()[0] == workspace.resolve()


def test_workspace_roots_defaults_without_config(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """With no configuration the process cwd bounds the paths."""
    monkeypatch.delenv(pc.WORKSPACE_ROOT_ENV, raising=False)
    monkeypatch.chdir(tmp_path)

    roots = pc.workspace_roots()

    assert roots[0] == tmp_path.resolve()
    assert pc.DEFAULT_WORKSPACE_ROOT == "/workspace"


def test_rejection_is_a_client_error(workspace: Path) -> None:
    """``errors.handle_error`` renders SpHTTPException verbatim, so a 400
    status on the raised error is the status the caller receives."""
    from signalpilot._utils.http import is_client_error

    with pytest.raises(HTTPException) as excinfo:
        pc.confine("/tmp/outside-workspace", label="parentDir")

    assert excinfo.value.status_code == 400
    assert is_client_error(excinfo.value.status_code)
    assert "parentDir" in (excinfo.value.detail or "")
