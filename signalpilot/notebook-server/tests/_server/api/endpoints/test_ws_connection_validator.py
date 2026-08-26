from signalpilot._server.api.endpoints.ws.analysis_trails import (
    is_generated_analysis_trail_notebook,
)


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
