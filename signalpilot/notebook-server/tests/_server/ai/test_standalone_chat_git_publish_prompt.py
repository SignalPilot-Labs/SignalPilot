"""The 'Publish your work' prompt section and the pull request tool allowlist."""

from __future__ import annotations

from signalpilot._server.api.endpoints.standalone_chat_prompt import (
    STANDALONE_ALLOWED_TOOLS,
    STANDALONE_SYSTEM_PROMPT,
    _execution_prompt_values,
    _load_prompt,
    git_publish_section,
)


def _prompt(**kwargs: object) -> str:
    *_, system_prompt = _execution_prompt_values(
        {"prompt": "Fix the revenue model"},
        project_id="project-a",
        branch=str(kwargs.pop("branch", "main")),
        commit_sha="a" * 40,
        connection_name="warehouse",
        **kwargs,  # type: ignore[arg-type]
    )
    return system_prompt


def test_publish_section_is_always_present_with_the_base_branch() -> None:
    prompt = _prompt(branch="release/2026-09")
    assert "## Publish your work" in prompt
    assert "The base branch is `release/2026-09`." in " ".join(prompt.split())
    assert "{base_branch}" not in prompt
    # Sits before the frozen-context trailer.
    assert prompt.index("## Publish your work") < prompt.index(
        "Selected project: project-a"
    )


def test_publish_section_states_the_rules() -> None:
    flat = " ".join(git_publish_section("main").split())
    assert "`/workspace` is a git repository" in flat
    assert "Load the `github` skill before any git or pull request work" in flat
    assert "Run git commands with `sandbox_exec`" in flat
    assert "signalpilot/<short-name>" in flat
    assert "Do not force push" in flat
    assert "Do not delete branches" in flat
    assert "`open_pull_request`" in flat
    assert "`update_pull_request`" in flat
    assert "`comment_on_pull_request`" in flat
    assert "Put the pull request URL in your final answer" in flat
    assert "You cannot merge" in flat


def test_publish_section_style() -> None:
    raw = _load_prompt("git_publish_suffix.md")
    assert chr(0x2014) not in raw  # no em dashes in agent-facing text
    assert all(len(line) <= 80 for line in raw.splitlines())


def test_system_prompt_points_at_the_workspace_checkout() -> None:
    assert "You have no git access" not in STANDALONE_SYSTEM_PROMPT
    assert "sandbox VM, at `/workspace`" in STANDALONE_SYSTEM_PROMPT


def test_pull_request_tools_are_allowed() -> None:
    assert {
        "mcp__signalpilot__open_pull_request",
        "mcp__signalpilot__update_pull_request",
        "mcp__signalpilot__comment_on_pull_request",
    } <= set(STANDALONE_ALLOWED_TOOLS)
