"""Unit tests for agent/prompt.py.

Covers:
- _load() internals via mocked filesystem (primary and fallback directories)
- load_agent_prompt(name) loading from prompts/agent-{name}.md
- build_continuation_prompt() returning file contents
- build_ceo_continuation() — format string substitution and _safe() injection protection
- _safe() brace-escaping behaviour (exercised through build_ceo_continuation)
- build_system_prompt() duration formatting and custom focus injection
- build_stop_prompt() with and without a reason
"""

import sys
from pathlib import Path
from unittest.mock import MagicMock, patch, mock_open, call

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import agent.prompt as prompt_module
from agent.prompt import (
    load_agent_prompt,
    build_continuation_prompt,
    build_ceo_continuation,
    build_stop_prompt,
    build_system_prompt,
    build_initial_prompt,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_minimal_ceo_kwargs(**overrides):
    """Return a complete set of keyword arguments for build_ceo_continuation."""
    defaults = dict(
        round_num=1,
        elapsed_minutes=10.0,
        duration_minutes=60.0,
        tool_summary="Bash, Read",
        files_changed="src/main.py",
        commits="abc1234 fix: typo",
        cost_so_far=0.05,
        round_summary="Fixed a bug.",
        original_prompt="Improve the codebase.",
    )
    defaults.update(overrides)
    return defaults


def _ceo_template_with_all_placeholders() -> str:
    """Minimal template that exercises every placeholder used by build_ceo_continuation."""
    return (
        "round={round_num} elapsed={elapsed} duration={duration} "
        "pct={pct_complete} tools={tool_summary} files={files_changed} "
        "commits={commits} cost={cost_so_far} summary={round_summary} "
        "prompt={original_prompt}"
    )


# ---------------------------------------------------------------------------
# 1. load_agent_prompt — happy path (primary directory hit)
# ---------------------------------------------------------------------------

class TestLoadAgentPrompt:
    def test_returns_stripped_file_content(self, tmp_path):
        """load_agent_prompt reads and strips the correct markdown file."""
        prompts_dir = tmp_path / "prompts"
        prompts_dir.mkdir()
        agent_file = prompts_dir / "agent-coder.md"
        agent_file.write_text("  You are a coder.  \n", encoding="utf-8")

        with patch.object(prompt_module, "_PROMPTS_DIR", prompts_dir):
            result = load_agent_prompt("coder")

        assert result == "You are a coder."

    def test_constructs_correct_filename(self, tmp_path):
        """load_agent_prompt builds the filename as agent-{name}.md."""
        prompts_dir = tmp_path / "prompts"
        prompts_dir.mkdir()
        (prompts_dir / "agent-reviewer.md").write_text("Reviewer prompt.", encoding="utf-8")

        with patch.object(prompt_module, "_PROMPTS_DIR", prompts_dir):
            result = load_agent_prompt("reviewer")

        assert result == "Reviewer prompt."

    def test_falls_back_to_secondary_directory(self, tmp_path):
        """load_agent_prompt falls back to _FALLBACK_DIR when primary doesn't have the file."""
        primary_dir = tmp_path / "primary"
        primary_dir.mkdir()
        fallback_dir = tmp_path / "fallback"
        fallback_dir.mkdir()
        (fallback_dir / "agent-qa.md").write_text("QA prompt.", encoding="utf-8")

        with patch.object(prompt_module, "_PROMPTS_DIR", primary_dir), \
             patch.object(prompt_module, "_FALLBACK_DIR", fallback_dir):
            result = load_agent_prompt("qa")

        assert result == "QA prompt."

    def test_raises_file_not_found_for_missing_agent(self, tmp_path):
        """load_agent_prompt raises FileNotFoundError when no file exists in either directory."""
        empty_dir = tmp_path / "empty"
        empty_dir.mkdir()

        with patch.object(prompt_module, "_PROMPTS_DIR", empty_dir), \
             patch.object(prompt_module, "_FALLBACK_DIR", empty_dir):
            with pytest.raises(FileNotFoundError, match="agent-ghost.md"):
                load_agent_prompt("ghost")

    def test_primary_directory_takes_precedence_over_fallback(self, tmp_path):
        """Primary directory content is used when both directories contain the file."""
        primary_dir = tmp_path / "primary"
        primary_dir.mkdir()
        fallback_dir = tmp_path / "fallback"
        fallback_dir.mkdir()
        (primary_dir / "agent-researcher.md").write_text("Primary researcher.", encoding="utf-8")
        (fallback_dir / "agent-researcher.md").write_text("Fallback researcher.", encoding="utf-8")

        with patch.object(prompt_module, "_PROMPTS_DIR", primary_dir), \
             patch.object(prompt_module, "_FALLBACK_DIR", fallback_dir):
            result = load_agent_prompt("researcher")

        assert result == "Primary researcher."


# ---------------------------------------------------------------------------
# 2. build_continuation_prompt — delegates to _load
# ---------------------------------------------------------------------------

class TestBuildContinuationPrompt:
    def test_returns_continuation_default_content(self, tmp_path):
        """build_continuation_prompt returns the content of continuation-default.md."""
        prompts_dir = tmp_path / "prompts"
        prompts_dir.mkdir()
        (prompts_dir / "continuation-default.md").write_text(
            "Continue the session.", encoding="utf-8"
        )

        with patch.object(prompt_module, "_PROMPTS_DIR", prompts_dir):
            result = build_continuation_prompt()

        assert result == "Continue the session."

    def test_returns_string_type(self, tmp_path):
        """build_continuation_prompt always returns a str."""
        prompts_dir = tmp_path / "prompts"
        prompts_dir.mkdir()
        (prompts_dir / "continuation-default.md").write_text("ok", encoding="utf-8")

        with patch.object(prompt_module, "_PROMPTS_DIR", prompts_dir):
            result = build_continuation_prompt()

        assert isinstance(result, str)


# ---------------------------------------------------------------------------
# 3. _safe() — brace escaping (tested via build_ceo_continuation)
# ---------------------------------------------------------------------------

class TestSafeBraceEscaping:
    """
    The _safe() helper is a closure inside build_ceo_continuation. It escapes
    user-derived content with _safe() before passing it as a value to str.format().
    Because str.format() only interprets {{ / }} in the *template*, not in
    substituted values, the doubled braces survive into the final output string.
    That is the correct and safe behaviour: the original brace characters are
    preserved (as doubled sequences) and no KeyError is raised.

    These tests assert:
      a) no KeyError / IndexError is raised, and
      b) the content (with braces doubled by _safe) appears in the output.
    """

    def _run(self, **field_overrides):
        """Run build_ceo_continuation with a controlled template and return the result."""
        kwargs = _make_minimal_ceo_kwargs(**field_overrides)
        with patch.object(prompt_module, "_load", return_value=_ceo_template_with_all_placeholders()):
            return build_ceo_continuation(**kwargs)

    def test_braces_in_tool_summary_do_not_raise(self):
        """Curly braces in tool_summary must not cause a KeyError.
        _safe() doubles them; the output contains the doubled form."""
        result = self._run(tool_summary='{"key": "value"}')
        # _safe turns { -> {{ and } -> }}, so output contains doubled braces
        assert '{{"key": "value"}}' in result

    def test_braces_in_files_changed_do_not_raise(self):
        """Curly braces in files_changed must not cause a KeyError."""
        result = self._run(files_changed="src/{module}.py")
        assert "src/{{module}}.py" in result

    def test_braces_in_commits_do_not_raise(self):
        """Curly braces in commits must not cause a KeyError."""
        result = self._run(commits="fix: handle {edge} case")
        assert "fix: handle {{edge}} case" in result

    def test_braces_in_round_summary_do_not_raise(self):
        """Curly braces in round_summary must not cause a KeyError."""
        result = self._run(round_summary="Changed function(s) {foo, bar}.")
        assert "Changed function(s) {{foo, bar}}." in result

    def test_braces_in_original_prompt_do_not_raise(self):
        """Curly braces in original_prompt must not cause a KeyError."""
        result = self._run(original_prompt="Refactor {legacy} module.")
        assert "Refactor {{legacy}} module." in result

    def test_single_open_brace_escaped(self):
        """A lone { in user content is passed through without raising."""
        result = self._run(tool_summary="prefix { suffix")
        assert "prefix {{ suffix" in result

    def test_single_close_brace_escaped(self):
        """A lone } in user content is passed through without raising."""
        result = self._run(tool_summary="prefix } suffix")
        assert "prefix }} suffix" in result

    def test_json_blob_in_round_summary(self):
        """A multi-key JSON object in round_summary does not raise."""
        json_blob = '{"added": ["a.py", "b.py"], "removed": []}'
        # Should not raise — actual content has doubled braces in output
        result = self._run(round_summary=json_blob)
        assert isinstance(result, str)
        assert "added" in result

    def test_plain_content_without_braces_unchanged(self):
        """Content without braces is preserved exactly (no doubling needed)."""
        result = self._run(tool_summary="Bash Read Write")
        assert "Bash Read Write" in result

    def test_no_key_error_with_arbitrary_brace_content(self):
        """Any combination of braces in any user field must never raise KeyError."""
        dangerous_inputs = [
            "{0}",
            "{key}",
            "{{nested}}",
            "{!r}",
            "{:.2f}",
        ]
        for value in dangerous_inputs:
            # Must not raise
            result = self._run(tool_summary=value)
            assert isinstance(result, str)


# ---------------------------------------------------------------------------
# 4. build_ceo_continuation — numeric and structural correctness
# ---------------------------------------------------------------------------

class TestBuildCeoContinuation:
    def _run(self, **overrides):
        kwargs = _make_minimal_ceo_kwargs(**overrides)
        with patch.object(prompt_module, "_load", return_value=_ceo_template_with_all_placeholders()):
            return build_ceo_continuation(**kwargs)

    def test_round_num_substituted(self):
        result = self._run(round_num=5)
        assert "round=5" in result

    def test_elapsed_minutes_formatted_as_integer_string(self):
        result = self._run(elapsed_minutes=15.0, duration_minutes=60.0)
        assert "elapsed=15m" in result

    def test_duration_minutes_formatted(self):
        result = self._run(duration_minutes=90.0, elapsed_minutes=10.0)
        assert "duration=90m" in result

    def test_pct_complete_calculated_correctly(self):
        # 30 of 60 minutes elapsed → 50%
        result = self._run(elapsed_minutes=30.0, duration_minutes=60.0)
        assert "pct=50" in result

    def test_pct_complete_capped_at_100(self):
        # More elapsed than duration → capped at 100
        result = self._run(elapsed_minutes=120.0, duration_minutes=60.0)
        assert "pct=100" in result

    def test_cost_formatted_to_two_decimal_places(self):
        result = self._run(cost_so_far=1.5)
        assert "cost=1.50" in result

    def test_zero_duration_produces_unlimited_string(self):
        result = self._run(duration_minutes=0, elapsed_minutes=5.0)
        assert "duration=unlimited" in result

    def test_zero_duration_pct_is_zero(self):
        result = self._run(duration_minutes=0, elapsed_minutes=5.0)
        assert "pct=0" in result

    def test_none_tool_summary_replaced_with_none_literal(self):
        result = self._run(tool_summary=None)
        assert "tools=none" in result

    def test_none_files_changed_replaced_with_none_literal(self):
        result = self._run(files_changed=None)
        assert "files=none" in result

    def test_none_commits_replaced_with_none_literal(self):
        result = self._run(commits=None)
        assert "commits=none" in result

    def test_none_round_summary_replaced_with_default(self):
        result = self._run(round_summary=None)
        assert "summary=No summary available." in result

    def test_none_original_prompt_replaced_with_default(self):
        result = self._run(original_prompt=None)
        assert "General self-improvement pass" in result

    def test_returns_string(self):
        result = self._run()
        assert isinstance(result, str)


# ---------------------------------------------------------------------------
# 5. build_system_prompt — duration formatting and custom focus
# ---------------------------------------------------------------------------

class TestBuildSystemPrompt:
    def _patch_load(self, content="base"):
        """Patch _load to return a fixed string for any filename."""
        return patch.object(prompt_module, "_load", return_value=content)

    def test_no_duration_no_focus_returns_dict(self):
        with self._patch_load():
            result = build_system_prompt()
        assert isinstance(result, dict)
        assert result["type"] == "preset"
        assert result["preset"] == "claude_code"

    def test_custom_focus_appended_to_output(self):
        with self._patch_load("system content"):
            result = build_system_prompt(custom_focus="Focus on tests.")
        assert "Focus on tests." in result["append"]

    def test_duration_under_60_formatted_as_minutes(self):
        with self._patch_load("t {duration}"):
            result = build_system_prompt(duration_minutes=45)
        assert "45m" in result["append"]

    def test_duration_exactly_60_formatted_as_hours_only(self):
        with self._patch_load("t {duration}"):
            result = build_system_prompt(duration_minutes=60)
        assert "1h" in result["append"]
        assert "0m" not in result["append"]

    def test_duration_90_formatted_as_hours_and_minutes(self):
        with self._patch_load("t {duration}"):
            result = build_system_prompt(duration_minutes=90)
        assert "1h 30m" in result["append"]

    def test_zero_duration_omits_duration_block(self):
        """When duration_minutes == 0, the timed-session block is not included."""
        load_calls = []

        def tracking_load(name):
            load_calls.append(name)
            return "content"

        with patch.object(prompt_module, "_load", side_effect=tracking_load):
            build_system_prompt(duration_minutes=0)

        assert "timed-session" not in load_calls


# ---------------------------------------------------------------------------
# 6. build_stop_prompt — with and without a reason
# ---------------------------------------------------------------------------

class TestBuildStopPrompt:
    def test_no_reason_returns_base_content(self, tmp_path):
        prompts_dir = tmp_path / "prompts"
        prompts_dir.mkdir()
        (prompts_dir / "stop.md").write_text("Stop now.", encoding="utf-8")

        with patch.object(prompt_module, "_PROMPTS_DIR", prompts_dir):
            result = build_stop_prompt()

        assert result == "Stop now."

    def test_with_reason_prepends_reason(self, tmp_path):
        prompts_dir = tmp_path / "prompts"
        prompts_dir.mkdir()
        (prompts_dir / "stop.md").write_text("Stop now.", encoding="utf-8")

        with patch.object(prompt_module, "_PROMPTS_DIR", prompts_dir):
            result = build_stop_prompt(reason="timeout")

        assert result.startswith("Stop reason: timeout")
        assert "Stop now." in result

    def test_empty_reason_returns_base_content(self, tmp_path):
        prompts_dir = tmp_path / "prompts"
        prompts_dir.mkdir()
        (prompts_dir / "stop.md").write_text("Stop now.", encoding="utf-8")

        with patch.object(prompt_module, "_PROMPTS_DIR", prompts_dir):
            result = build_stop_prompt(reason="")

        assert result == "Stop now."


# ---------------------------------------------------------------------------
# 7. build_initial_prompt — delegates to _load("initial")
# ---------------------------------------------------------------------------

class TestBuildInitialPrompt:
    def test_returns_initial_file_content(self, tmp_path):
        prompts_dir = tmp_path / "prompts"
        prompts_dir.mkdir()
        (prompts_dir / "initial.md").write_text("Start here.", encoding="utf-8")

        with patch.object(prompt_module, "_PROMPTS_DIR", prompts_dir):
            result = build_initial_prompt()

        assert result == "Start here."
