"""Verify that stored credentials restrict evaluation runs to one warehouse.

The evaluated agent must access only its assigned warehouse. The stored API key
contains this restriction because the evaluated agent controls request headers.

The tests import gateway modules after the database fixture initializes the
required tables.
"""

from __future__ import annotations

import pathlib

import pytest

PINNED = "northwind-eval"
GOOD_COPY = "northwind-demo"


def _pin_var():
    from gateway.mcp.context import mcp_eval_connection_var

    return mcp_eval_connection_var


def _validate(name: str):
    from gateway.mcp.validation import _validate_connection_name

    return _validate_connection_name(name)


def _scope(*headers: tuple[bytes, bytes]) -> dict:
    return {"headers": list(headers)}


@pytest.fixture(autouse=True)
def _clear_pin():
    var = _pin_var()
    token = var.set(None)
    yield
    var.reset(token)


class TestPinComesFromTheKeyNotTheRequest:
    """Verify that the caller cannot remove the stored connection restriction."""

    def test_header_extraction_no_longer_exists(self) -> None:
        """Verify that request headers cannot define the connection restriction."""
        import gateway.auth.mcp_api_key as mod

        for gone in (
            "_extract_eval_connection",
            "_extract_eval_doc_ids",
            "_extract_eval_run_task",
        ):
            assert not hasattr(mod, gone), (
                f"{gone} is back — the eval pin must come from the stored key, "
                "not from a request header the agent controls"
            )

    def test_the_runner_sends_no_eval_headers(self) -> None:
        """Verify that the MCP config contains the key without a pin header."""
        import inspect

        from gateway.evals import runner

        src = inspect.getsource(runner._mcp_json)
        assert "X-API-Key" in src
        for header in ("X-SP-Eval-Connection", "X-SP-Eval-Docs", "X-SP-Eval-Run", "X-SP-Eval-Task"):
            assert header not in src, f"{header} is being sent again"

    def test_key_record_carries_the_binding(self) -> None:
        from gateway.models.api_keys import ApiKeyRecord

        rec = ApiKeyRecord(
            id="k1",
            name="eval-run-1-t1",
            prefix="sp_x",
            key_hash="h",
            scopes=["read"],
            created_at="2026-01-01T00:00:00+00:00",
            eval_run_id="run-1",
            eval_task_id="t1",
            eval_connection=PINNED,
            eval_doc_ids=["d1"],
        )
        assert rec.eval_connection == PINNED
        assert rec.eval_run_id == "run-1"

    def test_unbound_key_carries_no_pin(self) -> None:
        """Verify that a workspace key has no evaluation connection restriction."""
        from gateway.models.api_keys import ApiKeyRecord

        rec = ApiKeyRecord(
            id="k2",
            name="user key",
            prefix="sp_y",
            key_hash="h",
            scopes=["read"],
            created_at="2026-01-01T00:00:00+00:00",
        )
        assert rec.eval_connection is None
        assert rec.eval_run_id is None


class TestValidatorEnforcesThePin:
    def test_pinned_connection_is_allowed(self) -> None:
        _pin_var().set(PINNED)
        assert _validate(PINNED) is None

    def test_the_good_copy_is_refused(self) -> None:
        _pin_var().set(PINNED)
        assert _validate(GOOD_COPY) is not None

    def test_every_other_connection_is_refused(self) -> None:
        _pin_var().set(PINNED)
        for other in ("prod-warehouse", "parallax-demo", "northwind_demo", "NORTHWIND-EVAL"):
            assert _validate(other) is not None, other

    def test_refusal_does_not_enumerate_the_workspace(self) -> None:
        """Verify that a refusal does not list other connection names."""
        _pin_var().set(PINNED)
        err = _validate(GOOD_COPY) or ""
        assert "Available" not in err
        # The response contains only the refused name and the assigned name.
        assert err.count("'") == 4

    def test_no_pin_leaves_normal_access_untouched(self) -> None:
        assert _validate(GOOD_COPY) is None
        assert _validate(PINNED) is None

    def test_shape_validation_still_applies_under_a_pin(self) -> None:
        _pin_var().set(PINNED)
        assert _validate("has space") is not None
        assert _validate("") is not None


class TestPinReachesEveryConnectionTakingTool:
    """Verify the restriction for each MCP tool that accepts a connection."""

    @staticmethod
    def _tools_root() -> pathlib.Path:
        return pathlib.Path(__file__).resolve().parents[1] / "gateway" / "mcp" / "tools"

    def test_all_connection_tools_route_through_the_validator(self) -> None:
        offenders = [
            str(p.relative_to(self._tools_root()))
            for p in self._tools_root().rglob("*.py")
            if "connection_name: str" in (src := p.read_text(encoding="utf-8", errors="replace"))
            and "_validate_connection_name" not in src
        ]
        assert not offenders, f"connection-taking tools bypassing the pin: {offenders}"

    def test_no_tool_hand_rolls_the_shape_check(self) -> None:
        """Verify that each tool uses _validate_connection_name."""
        offenders = [
            str(p.relative_to(self._tools_root()))
            for p in self._tools_root().rglob("*.py")
            if "_CONN_NAME_RE.match" in p.read_text(encoding="utf-8", errors="replace")
        ]
        assert not offenders, f"tools matching the regex directly, bypassing the pin: {offenders}"
