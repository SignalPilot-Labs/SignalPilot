"""Verify the warehouse branch lifecycle in gateway/evals/branches.py.

The tests verify names, quotas, and refusal paths. They use a provider test
double and do not connect to a warehouse.
"""

from __future__ import annotations

import re
from unittest.mock import AsyncMock

import pytest

from gateway.evals.branches import (
    EVAL_BRANCH_PREFIX,
    BranchError,
    BranchQuotaExceeded,
    PostgresBranchProvider,
    branch_name_for,
    enforce_branch_quota,
    run_suffix_of,
)

RUN = "run-20260101-010101-abc123"


class TestBranchNameFor:
    def test_shape(self) -> None:
        name = branch_name_for(RUN, "t1")
        assert name.startswith("eval-abc123-t1-")
        assert re.fullmatch(r"eval-abc123-t1-[0-9a-f]{6}", name), name

    def test_lowercases_and_sanitizes(self) -> None:
        assert branch_name_for(RUN, "T1:Fan/Out").startswith("eval-abc123-t1-fan-out-")

    def test_normalization_collisions_get_distinct_branches(self) -> None:
        """Verify that a digest separates equal flattened name segments.

        Each write task requires a distinct branch for isolation.
        """
        a = branch_name_for(RUN, "foo.bar")
        b = branch_name_for(RUN, "foo_bar")
        assert a != b
        assert a.startswith("eval-abc123-foo-bar-")
        assert b.startswith("eval-abc123-foo-bar-")

    def test_same_task_is_stable(self) -> None:
        assert branch_name_for(RUN, "foo.bar") == branch_name_for(RUN, "foo.bar")

    def test_prefix_is_the_eval_prefix(self) -> None:
        assert branch_name_for(RUN, "x").startswith(EVAL_BRANCH_PREFIX)
        assert not branch_name_for(RUN, "x").startswith("demo-")

    def test_task_segment_is_bounded(self) -> None:
        # Keep the prefix, run, task, and digest within the 63-character limit.
        name = branch_name_for(RUN, "x" * 200)
        assert len(name) <= 63

    def test_empty_task_id_still_yields_a_name(self) -> None:
        assert branch_name_for(RUN, "///").startswith("eval-abc123-task-")

    def test_run_suffix_is_the_last_run_id_segment(self) -> None:
        assert branch_name_for("run-20260101-010101-ffffff", "t").startswith("eval-ffffff-t-")


class TestRunSuffixOf:
    def test_roundtrip(self) -> None:
        assert run_suffix_of(branch_name_for(RUN, "t1-fan-out")) == "abc123"

    def test_non_eval_branch_is_empty(self) -> None:
        assert run_suffix_of("demo-abc123-x") == ""
        assert run_suffix_of("main") == ""
        assert run_suffix_of("") == ""


class _FakeProvider:
    def __init__(self, branches: list[str]) -> None:
        self._branches = branches

    async def list_eval_branches(self) -> list[str]:
        return list(self._branches)


class TestBranchQuota:
    async def test_below_the_ceiling_passes(self) -> None:
        await enforce_branch_quota(_FakeProvider(["eval-a-1"] * 4), ceiling=5)

    async def test_at_the_ceiling_refuses(self) -> None:
        with pytest.raises(BranchQuotaExceeded, match="ceiling 5"):
            await enforce_branch_quota(_FakeProvider(["eval-a-1"] * 5), ceiling=5)

    async def test_over_the_ceiling_refuses(self) -> None:
        with pytest.raises(BranchQuotaExceeded):
            await enforce_branch_quota(_FakeProvider(["b"] * 7), ceiling=5)


class TestPostgresIdent:
    @pytest.mark.parametrize("name", ["eval-abc123-t1", "northwind", "a_b-c1"])
    def test_safe_names_are_quoted(self, name: str) -> None:
        assert PostgresBranchProvider._ident(name) == f'"{name}"'

    @pytest.mark.parametrize(
        "bad",
        [
            "",
            "UPPER",
            "has space",
            'quo"te',
            "semi;colon",
            "dotted.name",
            "x" * 64,  # This name exceeds the PostgreSQL identifier limit.
            "back\\slash",
        ],
    )
    def test_unsafe_names_are_refused(self, bad: str) -> None:
        with pytest.raises(BranchError, match="unsafe database name"):
            PostgresBranchProvider._ident(bad)


class TestPostgresDelete:
    async def test_refuses_to_drop_a_non_eval_database(self) -> None:
        """Verify that validation rejects the request before a connection attempt.

        The test uses an unreachable DSN.
        """
        provider = PostgresBranchProvider("postgresql://nobody@nowhere/x", "parent")
        with pytest.raises(BranchError, match="refusing to drop non-eval database"):
            await provider.delete("northwind_demo")
        with pytest.raises(BranchError):
            await provider.delete("demo-abc123")


class TestPostgresRoleIsolation:
    async def test_role_mint_refuses_public_connect_to_other_databases(self, monkeypatch) -> None:
        provider = PostgresBranchProvider("postgresql://admin@db/postgres", "parent")
        admin = AsyncMock()
        admin.fetch.return_value = [{"datname": "parent"}, {"datname": "postgres"}]
        monkeypatch.setattr(provider, "_admin_conn", AsyncMock(return_value=admin))

        with pytest.raises(BranchError, match="PUBLIC CONNECT"):
            await provider._mint_branch_role("eval-abc123-task-123456")

        isolation_sql = admin.fetch.await_args.args[0]
        assert "NOT datistemplate" in isolation_sql
        assert any("DROP ROLE IF EXISTS" in call.args[0] for call in admin.execute.await_args_list)
        admin.close.assert_awaited_once()
