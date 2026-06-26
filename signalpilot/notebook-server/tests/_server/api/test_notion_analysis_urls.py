from __future__ import annotations

from signalpilot._server.api.endpoints import notion_urls


def test_trail_url_uses_sp_web_url_not_runtime_proxy(monkeypatch) -> None:
    monkeypatch.setenv("SP_WEB_URL", "https://app.signalpilot.ai")

    url = notion_urls.trail_url(
        "signalpilot-notion-analyses/analysis.py",
        "session-notion-abc123",
        "http://10.0.0.5:2718/notebook/runtime-session-1/",
    )

    expected = (
        "https://app.signalpilot.ai/projects?"
        "file=signalpilot-notion-analyses/analysis.py"
        "&session_id=session-notion-abc123"
    )
    assert url == expected
    assert "/notebook/runtime-session-1/notebooks" not in url


def test_trail_url_uses_project_url_when_project_context_is_available(monkeypatch) -> None:
    monkeypatch.setenv("SP_WEB_URL", "https://app.signalpilot.ai")

    url = notion_urls.trail_url(
        "notebooks/slack/hello-e45ede.py",
        "session-slack-abc123",
        "http://10.0.0.5:2718/notebook/runtime-session-1/",
        project_id="ba67f74b-370d-4200-82b0-863b2bc764eb",
        branch="analysis/slack/slack-4abe122a06e45ede-hello",
    )

    expected = (
        "https://app.signalpilot.ai/projects?"
        "project=ba67f74b-370d-4200-82b0-863b2bc764eb"
        "&branch=analysis/slack/slack-4abe122a06e45ede-hello"
        "&file=notebooks/slack/hello-e45ede.py"
    )
    assert url == expected
    assert "session_id=" not in url


def test_notebooks_base_url_appends_projects_to_runtime_fallback(monkeypatch) -> None:
    monkeypatch.delenv("SP_WEB_URL", raising=False)

    url = notion_urls.notebooks_base_url(
        "http://localhost:2718/notebook/runtime-session-1/"
    )

    assert url == "http://localhost:2718/notebook/runtime-session-1/projects"
