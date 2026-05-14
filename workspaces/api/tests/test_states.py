"""Tests for the RunState machine."""

from __future__ import annotations

import pytest

from workspaces_api.errors import IllegalTransition
from workspaces_api.states import RunState, transition


class TestStates:
    def test_queued_to_running_is_legal(self) -> None:
        result = transition(RunState.queued, RunState.running)
        assert result == RunState.running

    def test_queued_to_failed_is_legal(self) -> None:
        result = transition(RunState.queued, RunState.failed)
        assert result == RunState.failed

    def test_running_to_awaiting_approval_is_legal(self) -> None:
        result = transition(RunState.running, RunState.awaiting_approval)
        assert result == RunState.awaiting_approval

    def test_running_to_succeeded_is_legal(self) -> None:
        result = transition(RunState.running, RunState.succeeded)
        assert result == RunState.succeeded

    def test_running_to_failed_is_legal(self) -> None:
        result = transition(RunState.running, RunState.failed)
        assert result == RunState.failed

    def test_running_to_cancelled_is_legal(self) -> None:
        result = transition(RunState.running, RunState.cancelled)
        assert result == RunState.cancelled

    def test_awaiting_approval_to_running_is_legal(self) -> None:
        result = transition(RunState.awaiting_approval, RunState.running)
        assert result == RunState.running

    def test_awaiting_approval_to_cancelled_is_legal(self) -> None:
        result = transition(RunState.awaiting_approval, RunState.cancelled)
        assert result == RunState.cancelled

    def test_succeeded_to_running_is_illegal(self) -> None:
        with pytest.raises(IllegalTransition):
            transition(RunState.succeeded, RunState.running)

    def test_failed_to_running_is_illegal(self) -> None:
        with pytest.raises(IllegalTransition):
            transition(RunState.failed, RunState.running)

    def test_cancelled_to_running_is_illegal(self) -> None:
        with pytest.raises(IllegalTransition):
            transition(RunState.cancelled, RunState.running)

    def test_queued_to_succeeded_is_illegal(self) -> None:
        with pytest.raises(IllegalTransition):
            transition(RunState.queued, RunState.succeeded)

    def test_queued_to_awaiting_approval_is_illegal(self) -> None:
        with pytest.raises(IllegalTransition):
            transition(RunState.queued, RunState.awaiting_approval)
