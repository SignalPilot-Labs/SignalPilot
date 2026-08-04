"""Verify delivery of an evaluation set CLAUDE.md file to each task container.

The task receives the dbt project from SP_PROJECT_TARBALL_URL. The runner writes
the evaluation instructions after project extraction so they take precedence.
"""

from __future__ import annotations

import base64
import re

import pytest


def _spec(**kw):
    from gateway.config.evals import get_eval_run_settings
    from gateway.evals.runner import _task_spec

    settings = get_eval_run_settings()
    return _task_spec(
        settings,
        prompt="q",
        model="sonnet",
        mcp_json='{"mcpServers":{}}',
        labels={"run": "r", "question": "q"},
        **kw,
    )


@pytest.fixture(autouse=True)
def _settings(monkeypatch: pytest.MonkeyPatch):
    from gateway.config.evals import get_eval_run_settings

    monkeypatch.setenv("SP_EVAL_RUNNER_IMAGE", "example.com/runner@sha256:" + "a" * 64)
    get_eval_run_settings.cache_clear()
    yield
    get_eval_run_settings.cache_clear()


class TestItRidesAsEnv:
    def test_present_when_the_set_ships_one(self) -> None:
        spec = _spec(claude_md="# Northwind\nMarts are service-line grain.\n")
        raw = spec.env["SP_CLAUDE_MD_B64"]
        assert base64.b64decode(raw).decode() == "# Northwind\nMarts are service-line grain.\n"

    def test_absent_when_the_set_ships_none(self) -> None:
        assert "SP_CLAUDE_MD_B64" not in _spec().env
        assert "SP_CLAUDE_MD_B64" not in _spec(claude_md="   \n  ").env

    def test_it_is_not_on_the_secret_channel(self) -> None:
        """Project instructions are not a credential; keeping them out of the
        secret channel means they show up in the sandbox panel like other env."""
        spec = _spec(claude_md="# ctx")
        assert "SP_CLAUDE_MD_B64" in spec.env
        assert "SP_CLAUDE_MD_B64" not in spec.secret_env

    def test_base64_survives_newlines_and_quotes(self) -> None:
        """The value crosses env -> shell -> file; raw text would not survive."""
        tricky = '# Ctx\n\n"quoted" \'single\' $VAR `cmd`\nline\twith\ttabs\n'
        spec = _spec(claude_md=tricky)
        assert base64.b64decode(spec.env["SP_CLAUDE_MD_B64"]).decode() == tricky


class TestTheProjectTarball:
    def test_tarball_url_rides_the_secret_channel(self) -> None:
        """Verify that the presigned URL does not appear in container metadata."""
        spec = _spec(project_tarball_url="https://s3/x?sig=abc")
        assert spec.secret_env["SP_PROJECT_TARBALL_URL"] == "https://s3/x?sig=abc"
        assert "SP_PROJECT_TARBALL_URL" not in spec.env

    def test_absent_tarball_sets_nothing(self) -> None:
        spec = _spec()
        assert "SP_PROJECT_TARBALL_URL" not in spec.secret_env

    def test_the_script_fetches_over_curl_not_git(self) -> None:
        """Verify that the pod receives no Git credential."""
        from gateway.evals.runner import _RUNNER_SCRIPT

        assert "SP_PROJECT_TARBALL_URL" in _RUNNER_SCRIPT
        assert "curl" in _RUNNER_SCRIPT
        assert "SP_PROJECT_REPO" not in _RUNNER_SCRIPT


class TestTheRunnerScript:
    def test_writes_claude_md_when_set(self) -> None:
        from gateway.evals.runner import _RUNNER_SCRIPT

        assert "/work/CLAUDE.md" in _RUNNER_SCRIPT
        assert "SP_CLAUDE_MD_B64" in _RUNNER_SCRIPT

    def test_absent_claude_md_does_not_break_the_chain(self) -> None:
        """Verify that an absent CLAUDE.md does not stop task execution.

        A failed condition in the command chain must not prevent the Claude command.
        """
        from gateway.evals.runner import _RUNNER_SCRIPT

        guard = re.search(r"\{[^}]*SP_CLAUDE_MD_B64[^}]*\}", _RUNNER_SCRIPT)
        assert guard, "the CLAUDE.md write is not wrapped in a group"
        assert "true;" in guard.group(0), "group must end in `true` so absence is not a failure"

    def test_absent_tarball_does_not_break_the_chain(self) -> None:
        """Verify that an absent project repository does not stop task execution."""
        from gateway.evals.runner import _RUNNER_SCRIPT

        guard = re.search(r"\{[^}]*SP_PROJECT_TARBALL_URL[^}]*\}", _RUNNER_SCRIPT)
        assert guard, "the tarball fetch is not wrapped in a group"
        assert "true;" in guard.group(0)

    def test_claude_still_runs_after_the_write(self) -> None:
        from gateway.evals.runner import _RUNNER_SCRIPT

        assert _RUNNER_SCRIPT.index("SP_CLAUDE_MD_B64") < _RUNNER_SCRIPT.index("claude -p")

    def test_claude_md_lands_after_the_tarball_unpack(self) -> None:
        """Verify that evaluation instructions replace project instructions."""
        from gateway.evals.runner import _RUNNER_SCRIPT

        assert _RUNNER_SCRIPT.index("SP_PROJECT_TARBALL_URL") < _RUNNER_SCRIPT.index(
            "SP_CLAUDE_MD_B64"
        )
