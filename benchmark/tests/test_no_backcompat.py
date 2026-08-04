"""Verify that unsupported benchmark interfaces fail.

Unavailable import paths raise ModuleNotFoundError. Unsupported calling
conventions raise the documented argument or validation error.
"""

from __future__ import annotations

import importlib

import pytest


def test_run_kb_shim_is_gone() -> None:
    """Verify that benchmark.run_kb is unavailable."""
    with pytest.raises(ModuleNotFoundError):
        importlib.import_module("benchmark.run_kb")


def test_local_comparator_is_gone() -> None:
    """Verify that benchmark.evaluation.local_comparator is unavailable."""
    with pytest.raises(ModuleNotFoundError):
        importlib.import_module("benchmark.evaluation.local_comparator")


def test_prepare_sql_workdir_requires_skill_names() -> None:
    """Verify that prepare_sql_workdir requires skill_names."""
    from benchmark.core.suite import BenchmarkSuite, get_test_suite_config
    from benchmark.core.workdir import prepare_sql_workdir

    config = get_test_suite_config(BenchmarkSuite.LITE)
    with pytest.raises(TypeError):
        prepare_sql_workdir("lite_sqlite001", config, {})  # type: ignore[call-arg]


def test_determine_backend_requires_type_field() -> None:
    """Verify that backend selection requires an explicit type field."""
    sql_runner = pytest.importorskip(
        "benchmark.runners.sql_runner",
        reason="claude_agent_sdk not installed in this environment",
    )
    from benchmark.core.suite import BenchmarkSuite

    with pytest.raises(ValueError, match="missing the required 'type' field"):
        sql_runner._determine_backend(
            BenchmarkSuite.LITE, {"instance_id": "lite_x001", "db": "some_db"}
        )


def test_auto_scale_max_turns_is_gone() -> None:
    direct = pytest.importorskip(
        "benchmark.runners.direct",
        reason="claude_agent_sdk not installed in this environment",
    )
    assert not hasattr(direct, "_auto_scale_max_turns")
