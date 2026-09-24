"""The session flag the CLI refuses must select the other one.

`claude --session-id <id>` fails for an id the CLI already holds, and
`claude --resume <id>` fails for one it has never seen. Neither is safe to pick
from the filesystem alone, so these cover the recovery and the refusal to
recover silently.
"""

from __future__ import annotations

from signalpilot._server.ai.claude_agent import (
    _NO_CONVERSATION,
    _retry_with_resume,
    _session_lost_message,
)

IN_USE = "Error: Session ID 66666666-4444-4444-4444-666666666666 is already in use."
NOT_FOUND = "No conversation found with session ID: 66666666-4444-4444-4444-666666666666"


def test_an_id_already_in_use_retries_as_a_resume() -> None:
    assert _retry_with_resume(IN_USE, is_resume=False, started=False) is True


def test_the_retry_survives_surrounding_cli_noise() -> None:
    noisy = f"some warning\n{IN_USE}\nnode:internal/process\n"
    assert _retry_with_resume(noisy, is_resume=False, started=False) is True


def test_a_failed_resume_is_not_retried() -> None:
    # Retrying a resume as a new session would answer the user with no memory
    # of the conversation they are in.
    assert _retry_with_resume(NOT_FOUND, is_resume=True, started=False) is False


def test_nothing_is_retried_once_the_turn_has_streamed() -> None:
    # Re-running a turn that already produced output would duplicate it.
    assert _retry_with_resume(IN_USE, is_resume=False, started=True) is False


def test_an_unrelated_failure_is_not_retried() -> None:
    assert _retry_with_resume("ENOSPC: no space left on device", is_resume=False, started=False) is False


def test_empty_stderr_is_not_retried() -> None:
    assert _retry_with_resume("", is_resume=False, started=False) is False


def test_a_missing_conversation_is_recognised() -> None:
    assert _NO_CONVERSATION.search(NOT_FOUND)
    assert not _NO_CONVERSATION.search(IN_USE)


def test_the_lost_session_message_names_the_session_and_the_way_out() -> None:
    text = _session_lost_message("abc-123")
    assert "abc-123" in text
    assert "new conversation" in text
