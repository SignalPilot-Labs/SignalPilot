"""The 'Publish your work' prompt section and the pull request tool allowlist.

The five prompt files were consolidated into one `standalone_chat_system.md`
whose conditional sections are marked inline and sliced by flag, so these tests
now exercise the slicing rather than a separate suffix file. The publish
section is gated on `sandbox_runtime`: the tools it tells the agent to use
(`sandbox_exec`, `sandbox_write_file`) only exist behind that flag, and a chat
without it was previously told to call tools it did not have.
"""

from __future__ import annotations

from signalpilot._server.api.endpoints.standalone_chat_prompt import (
    STANDALONE_ALLOWED_TOOLS,
    STANDALONE_SYSTEM_PROMPT,
    _execution_prompt_values,
    _load_prompt,
    git_publish_section,
)


def _prose_lines(text: str) -> list[str]:
    """Lines the 80-column rule can fairly apply to.

    The rule was written for a 17-line suffix file. The consolidated prompt
    inherits markdown tables and long artifact links from the original
    sections, which cannot wrap without breaking rendering, so they are
    exempt rather than reflowed.
    """
    return [
        line
        for line in text.splitlines()
        if "|" not in line and "](" not in line
    ]


def _prompt(**kwargs: object) -> str:
    body: dict[str, object] = {"prompt": "Fix the revenue model"}
    features = kwargs.pop("features", {"sandbox_runtime": True})
    body["features"] = features
    *_, system_prompt = _execution_prompt_values(
        body,
        project_id="project-a",
        branch=str(kwargs.pop("branch", "main")),
        commit_sha="a" * 40,
        connection_name="warehouse",
        **kwargs,  # type: ignore[arg-type]
    )
    return system_prompt


def test_publish_section_present_with_the_base_branch_when_sandbox_is_on() -> None:
    prompt = _prompt(branch="release/2026-09")
    assert "## Publish your work" in prompt
    assert "The index points at the head of `release/2026-09`" in " ".join(
        prompt.split()
    )
    assert "{base_branch}" not in prompt
    # Sits before the frozen-context trailer.
    assert prompt.index("## Publish your work") < prompt.index(
        "Selected project: project-a"
    )


def test_publish_section_absent_without_the_sandbox_runtime() -> None:
    # The section names sandbox_exec and sandbox_write_file. Without the
    # feature those tools are not in the toolset, so the section must not
    # reach the agent.
    prompt = _prompt(features={})
    assert "## Publish your work" not in prompt
    assert "Push only to" not in prompt
    assert "open_pull_request" not in prompt
    # "Where you may write" still names the sandbox tools when explaining where
    # model edits happen. That mention is unconditional by design: it tells the
    # agent why its working directory is not the place to edit.


def test_publish_section_states_the_rules() -> None:
    flat = " ".join(git_publish_section("main").split())
    assert "turned into a git repository" in flat
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


def test_publish_section_states_the_unlinked_project_behaviour() -> None:
    # The git server ACCEPTS a push for a project with no GitHub link and
    # records it unpublished (gateway git/http_server.py:455-462); it is
    # open_pull_request that refuses (gateway git/agent_pr.py:234). An earlier
    # prompt claimed the push itself was refused.
    flat = " ".join(git_publish_section("main").split())
    assert "the push is accepted but not published" in flat
    assert "this project is not linked to GitHub" in flat


def test_prompt_style() -> None:
    raw = _load_prompt("standalone_chat_system.md")
    assert chr(0x2014) not in raw  # no em dashes in agent-facing text
    assert all(len(line) <= 80 for line in _prose_lines(raw))


def test_system_prompt_points_at_the_workspace_checkout() -> None:
    assert "You have no git access" not in STANDALONE_SYSTEM_PROMPT
    assert "sandbox VM at `/workspace`" in STANDALONE_SYSTEM_PROMPT


def test_working_directory_is_described_as_writable_but_checked() -> None:
    # It is NOT read-only: nothing blocks a write. The digest check runs once
    # after the last turn and rejects the answer, reverting nothing.
    flat = " ".join(STANDALONE_SYSTEM_PROMPT.split())
    assert "It is writable" in flat
    assert "the run ends with an error instead of your answer" in flat
    assert "Nothing is reverted" in flat


def test_pull_request_tools_are_allowed() -> None:
    assert {
        "mcp__signalpilot__open_pull_request",
        "mcp__signalpilot__update_pull_request",
        "mcp__signalpilot__comment_on_pull_request",
    } <= set(STANDALONE_ALLOWED_TOOLS)
