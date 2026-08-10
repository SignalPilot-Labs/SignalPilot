from pathlib import Path

from signalpilot._server.api.endpoints.ws.analysis_trails import (
    is_generated_analysis_trail_notebook,
)
from signalpilot._server.files.project_paths import resolve_project_file


def test_project_backed_slack_analysis_trail_is_lazy() -> None:
    assert is_generated_analysis_trail_notebook(
        project_id="907a47d1-b196-428b-89de-7f4a8b7acc41",
        branch="analysis/slack/slack-ba96530d8fb3514d-hi",
        file_key="notebooks/slack/hi-can-you-figure-out-if-our-fin-db.py",
    )


def test_project_backed_notion_analysis_trail_is_lazy() -> None:
    assert is_generated_analysis_trail_notebook(
        project_id="907a47d1-b196-428b-89de-7f4a8b7acc41",
        branch="analysis/notion/notion-ba96530d8fb3514d-hi",
        file_key="notebooks/notion/hi-can-you-figure-out-if-our-fin-db.py",
    )


def test_regular_project_notebook_keeps_runtime_default() -> None:
    assert not is_generated_analysis_trail_notebook(
        project_id="907a47d1-b196-428b-89de-7f4a8b7acc41",
        branch="main",
        file_key="notebooks/slack/handwritten-notebook.py",
    )


def test_non_analysis_notebook_under_analysis_branch_keeps_runtime_default() -> None:
    assert not is_generated_analysis_trail_notebook(
        project_id="907a47d1-b196-428b-89de-7f4a8b7acc41",
        branch="analysis/slack/slack-ba96530d8fb3514d-hi",
        file_key="notebooks/intro.py",
    )


def test_mismatched_analysis_source_keeps_runtime_default() -> None:
    assert not is_generated_analysis_trail_notebook(
        project_id="907a47d1-b196-428b-89de-7f4a8b7acc41",
        branch="analysis/notion/notion-ba96530d8fb3514d-hi",
        file_key="notebooks/slack/hi-can-you-figure-out-if-our-fin-db.py",
    )


def test_non_project_notebook_keeps_runtime_default() -> None:
    assert not is_generated_analysis_trail_notebook(
        project_id=None,
        branch="analysis/slack/slack-ba96530d8fb3514d-hi",
        file_key="notebooks/slack/hi-can-you-figure-out-if-our-fin-db.py",
    )


def test_resolve_project_file_requires_exact_relative_path(tmp_path: Path) -> None:
    notebook = tmp_path / "notebooks" / "intro.py"
    notebook.parent.mkdir()
    notebook.write_text("print('ready')", encoding="utf-8")

    assert resolve_project_file(tmp_path, "notebooks/intro.py") == str(
        notebook.resolve()
    )
    assert resolve_project_file(tmp_path, "other/intro.py") is None


def test_resolve_project_file_rejects_parent_traversal(tmp_path: Path) -> None:
    outside = tmp_path.parent / "outside.py"
    outside.write_text("print('outside')", encoding="utf-8")

    assert resolve_project_file(tmp_path, "../outside.py") is None
