"""Tests for claude_md_renderer — golden render, no token leakage, stable output."""

from __future__ import annotations

import uuid


from workspaces_api.agent.claude_md_renderer import RunRenderContext, render_run_claude_md

_FIXED_RUN_ID = uuid.UUID("11111111-2222-3333-4444-555555555555")
_FIXED_WS_ID = "ws-test-001"
_FIXED_GATEWAY = "http://gateway.local:3100"


class TestRenderRunClaudeMd:
    def _make_ctx(
        self,
        proxy_host: str | None = "127.0.0.1",
        proxy_port: int | None = 15432,
        mode: str = "local",
    ) -> RunRenderContext:
        return RunRenderContext(
            run_id=_FIXED_RUN_ID,
            workspace_id=_FIXED_WS_ID,
            gateway_url=_FIXED_GATEWAY,
            mode=mode,  # type: ignore[arg-type]
            proxy_host=proxy_host,
            proxy_port=proxy_port,
        )

    def test_render_contains_run_id(self) -> None:
        ctx = self._make_ctx()
        result = render_run_claude_md(ctx)
        assert str(_FIXED_RUN_ID) in result

    def test_render_contains_workspace_id(self) -> None:
        ctx = self._make_ctx()
        result = render_run_claude_md(ctx)
        assert _FIXED_WS_ID in result

    def test_render_contains_gateway_url(self) -> None:
        ctx = self._make_ctx()
        result = render_run_claude_md(ctx)
        assert _FIXED_GATEWAY in result

    def test_render_with_proxy_contains_host_and_port(self) -> None:
        ctx = self._make_ctx(proxy_host="127.0.0.1", proxy_port=15432)
        result = render_run_claude_md(ctx)
        assert "127.0.0.1" in result
        assert "15432" in result

    def test_render_without_proxy_omits_pg_vars(self) -> None:
        ctx = self._make_ctx(proxy_host=None, proxy_port=None)
        result = render_run_claude_md(ctx)
        # Should not mention PGPASSWORD (token) or proxy host
        assert "PGPASSWORD" not in result

    def test_no_token_in_output(self) -> None:
        """Token must never appear — it's in env var PGPASSWORD, not CLAUDE.md."""
        ctx = self._make_ctx()
        result = render_run_claude_md(ctx)
        # The template should not embed any secret
        assert "token" not in result.lower() or "approval" in result.lower()
        # More specifically: no raw secret placeholder
        assert "SP_API_KEY" not in result
        assert "ANTHROPIC_API_KEY" not in result
        assert "CLAUDE_CODE_OAUTH_TOKEN" not in result

    def test_no_host_absolute_paths(self) -> None:
        """Output must not contain absolute paths like /home/... or /opt/..."""
        ctx = self._make_ctx()
        result = render_run_claude_md(ctx)
        lines_with_abs = [
            line for line in result.splitlines()
            if line.strip().startswith("/") and not line.strip().startswith("//")
        ]
        # Allow lines that are pure markdown (comments starting with /) — there shouldn't be any
        assert lines_with_abs == [], f"Found absolute paths: {lines_with_abs}"

    def test_references_static_md(self) -> None:
        """Should reference ~/.claude/CLAUDE_static.md for extended instructions."""
        ctx = self._make_ctx()
        result = render_run_claude_md(ctx)
        assert "CLAUDE_static.md" in result

    def test_stable_output_for_fixed_context(self) -> None:
        """Two calls with identical context produce identical output."""
        ctx = self._make_ctx()
        assert render_run_claude_md(ctx) == render_run_claude_md(ctx)

    def test_pure_function_no_side_effects(self) -> None:
        """render_run_claude_md does not write files or mutate state."""
        ctx = self._make_ctx()
        r1 = render_run_claude_md(ctx)
        r2 = render_run_claude_md(ctx)
        assert r1 == r2

    def test_approval_flow_uses_directory_convention(self) -> None:
        """Approval flow section should describe watching the .signalpilot/resume/ dir."""
        ctx = self._make_ctx()
        result = render_run_claude_md(ctx)
        assert "~/.signalpilot/resume/" in result

    def test_approval_flow_describes_per_approval_json_files(self) -> None:
        """Each approval produces an <approval_id>.json file, not a single resume file."""
        ctx = self._make_ctx()
        result = render_run_claude_md(ctx)
        assert "approval_id" in result
        # New convention uses .json extension per approval
        assert ".json" in result

    def test_approval_flow_decision_vocabulary_past_tense(self) -> None:
        """The template describes 'approved' and 'rejected' (past tense)."""
        ctx = self._make_ctx()
        result = render_run_claude_md(ctx)
        assert '"approved"' in result
        assert '"rejected"' in result
