"""Verify SP_EVAL_PROJECT_ENV credentials for the dbt project.

The project profiles.yml reads connection values from environment variables.
The server supplies these credentials to each task container.
"""

from __future__ import annotations

import pytest


@pytest.fixture(autouse=True)
def _clear():
    from gateway.config.evals import get_eval_run_settings

    get_eval_run_settings.cache_clear()
    yield
    get_eval_run_settings.cache_clear()


def _settings(raw: str):
    import os

    from gateway.config.evals import get_eval_run_settings

    os.environ["SP_EVAL_PROJECT_ENV"] = raw
    os.environ["SP_EVAL_RUNNER_IMAGE"] = "example.com/r@sha256:" + "a" * 64
    get_eval_run_settings.cache_clear()
    return get_eval_run_settings()


class TestParsing:
    def test_newline_separated(self) -> None:
        env = _settings("A=1\nB=two").project_env
        assert env == {"A": "1", "B": "two"}

    def test_comma_separated(self) -> None:
        assert _settings("A=1,B=two").project_env == {"A": "1", "B": "two"}

    def test_blank_and_comments_ignored(self) -> None:
        assert _settings("\n# note\nA=1\n\n").project_env == {"A": "1"}

    def test_unset_is_empty(self) -> None:
        assert _settings("").project_env == {}

    def test_value_may_contain_equals(self) -> None:
        """Passwords and DSNs routinely contain '='; only the first splits."""
        env = _settings("PGPASSWORD=ab=cd==").project_env
        assert env["PGPASSWORD"] == "ab=cd=="

    def test_malformed_entries_are_skipped_not_fatal(self) -> None:
        assert _settings("JUSTAKEY\nA=1").project_env == {"A": "1"}


class TestItReachesTheContainer:
    def _spec(self, raw: str):
        from gateway.evals.runner import _task_spec

        return _task_spec(
            _settings(raw),
            prompt="q",
            model="sonnet",
            mcp_json='{"mcpServers":{}}',
            labels={"run": "r", "question": "q"},
        )

    def test_merged_into_secret_env(self) -> None:
        spec = self._spec("NORTHWIND_PG_HOST=h\nNORTHWIND_PG_PASSWORD=p")
        assert spec.secret_env["NORTHWIND_PG_HOST"] == "h"
        assert spec.secret_env["NORTHWIND_PG_PASSWORD"] == "p"

    def test_it_is_a_credential_not_plain_env(self) -> None:
        """Plain env shows up in `docker inspect` and pod specs; this must not."""
        spec = self._spec("NORTHWIND_PG_PASSWORD=p")
        assert "NORTHWIND_PG_PASSWORD" not in spec.env

    def test_it_cannot_clobber_the_mcp_config(self) -> None:
        """The MCP config carries the per-run API key and the eval pin; letting
        operator env replace it would unpin the run."""
        spec = self._spec("SP_MCP_JSON_B64=tampered")
        # Verify that project_env cannot replace the protected MCP config.
        assert spec.secret_env["SP_MCP_JSON_B64"] != "tampered", (
            "project_env overwrote the MCP config — merge it before SP_MCP_JSON_B64"
        )
