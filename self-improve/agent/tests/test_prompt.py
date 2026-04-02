"""Tests for the prompt loading module."""

import pytest

from agent import prompt


def test_build_system_prompt_returns_dict():
    result = prompt.build_system_prompt()
    assert isinstance(result, dict)
    assert result["type"] == "preset"
    assert result["preset"] == "claude_code"
    assert "append" in result


def test_build_system_prompt_includes_system_content():
    result = prompt.build_system_prompt()
    text = result["append"]
    # System prompt should include core agent instructions
    assert "principal engineer" in text or "self-improvement" in text.lower()


def test_build_system_prompt_with_custom_focus():
    result = prompt.build_system_prompt(custom_focus="Fix all security issues")
    text = result["append"]
    assert "Fix all security issues" in text
    assert "## Additional Focus" in text


def test_build_system_prompt_with_duration():
    result = prompt.build_system_prompt(duration_minutes=30)
    text = result["append"]
    assert "30m" in text


def test_build_system_prompt_duration_hours():
    result = prompt.build_system_prompt(duration_minutes=90)
    text = result["append"]
    assert "1h 30m" in text


def test_build_initial_prompt_returns_string():
    result = prompt.build_initial_prompt()
    assert isinstance(result, str)
    assert len(result) > 0


def test_build_initial_prompt_includes_workflow():
    result = prompt.build_initial_prompt()
    # Should mention exploring or improving the codebase
    assert "improv" in result.lower() or "explor" in result.lower()


def test_build_ceo_continuation_formats_variables():
    result = prompt.build_ceo_continuation(
        round_num=3,
        elapsed_minutes=15,
        duration_minutes=30,
        tool_summary="Bash: 5, Read: 10",
        files_changed="main.py, utils.py",
        commits="abc1234 Fix bug",
        cost_so_far=1.25,
        round_summary="Fixed a bug in the gateway",
        original_prompt="Improve the codebase",
    )
    assert "Round 3" in result
    assert "15m of 30m" in result
    assert "50%" in result
    assert "Bash: 5, Read: 10" in result
    assert "$1.25" in result
    assert "Improve the codebase" in result


def test_build_ceo_continuation_unlimited_duration():
    result = prompt.build_ceo_continuation(
        round_num=1,
        elapsed_minutes=5,
        duration_minutes=0,
        tool_summary="",
        files_changed="",
        commits="",
        cost_so_far=0,
        round_summary="",
        original_prompt="",
    )
    assert "unlimited" in result


def test_build_stop_prompt():
    result = prompt.build_stop_prompt()
    assert "commit" in result.lower()


def test_build_stop_prompt_with_reason():
    result = prompt.build_stop_prompt(reason="Operator requested stop")
    assert "Operator requested stop" in result


def test_load_missing_prompt_raises():
    with pytest.raises(FileNotFoundError):
        prompt._load("nonexistent-prompt-file")
