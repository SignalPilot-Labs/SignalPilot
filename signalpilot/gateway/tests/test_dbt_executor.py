"""dbt executor: arg sanitization, profile emitters, credential isolation."""

from __future__ import annotations

import pytest

from gateway.standalone_chat.dbt_executor import (
    DbtExecutorError,
    build_dbt_argv,
    emit_profile,
    scratch_schema_for,
)


# ── argv allowlist / sanitization ────────────────────────────────────────────


def test_argv_allows_known_commands():
    argv = build_dbt_argv("run", select="stg_orders+", dbt_dir="dbt")
    assert argv[:2] == ["dbt", "run"]
    assert "--profiles-dir" in argv and "/creds" in argv
    assert "--project-dir" in argv and "/workspace/dbt" in argv
    assert "--target" in argv and "sp" in argv
    assert argv[argv.index("--select") + 1] == "stg_orders+"


def test_argv_docs_generate_only():
    build_dbt_argv("docs generate", dbt_dir="")
    with pytest.raises(DbtExecutorError):
        build_dbt_argv("docs serve", dbt_dir="")


@pytest.mark.parametrize("cmd", ["drop", "rm -rf", "run; drop table x", "seed && curl evil"])
def test_argv_rejects_non_allowlisted(cmd):
    with pytest.raises(DbtExecutorError):
        build_dbt_argv(cmd, dbt_dir="")


@pytest.mark.parametrize("bad", ["stg; drop", "a`whoami`", "x$(id)", "--profiles-dir /etc"])
def test_argv_rejects_injection_in_selectors(bad):
    with pytest.raises(DbtExecutorError):
        build_dbt_argv("run", select=bad, dbt_dir="")


def test_argv_never_lets_caller_override_profiles_or_target():
    # Selectors are the only free text and they're regex-guarded; the command
    # itself must be a single subcommand.
    with pytest.raises(DbtExecutorError):
        build_dbt_argv("run --profiles-dir /tmp", dbt_dir="")


def test_argv_threads_clamped():
    argv = build_dbt_argv("run", threads=999, dbt_dir="")
    assert argv[argv.index("--threads") + 1] == "8"


# ── profile emitters ─────────────────────────────────────────────────────────


def test_postgres_profile_targets_scratch_schema():
    emitted = emit_profile(
        "postgres", "demo", "postgresql://u:p@host:5432/db?sslmode=require", "sp_chat_abc"
    )
    assert "type: postgres" in emitted.profile_yaml
    assert "schema: sp_chat_abc" in emitted.profile_yaml
    assert emitted.adapter_package == "dbt-postgres"


def test_snowflake_profile_parses_account_and_warehouse():
    emitted = emit_profile(
        "snowflake",
        "demo",
        "snowflake://user:pw@acct123/ANALYTICS?warehouse=WH&role=RPT",
        "sp_chat_xy",
    )
    assert "type: snowflake" in emitted.profile_yaml
    assert "account: acct123" in emitted.profile_yaml
    assert "warehouse: WH" in emitted.profile_yaml
    assert "schema: sp_chat_xy" in emitted.profile_yaml


def test_unsupported_db_type_is_a_clear_error():
    with pytest.raises(DbtExecutorError) as exc:
        emit_profile("mysql", "demo", "mysql://u:p@h/db", "sp_chat_1")
    assert "does not support" in str(exc.value)


def test_scratch_schema_is_deterministic_and_scoped():
    s = scratch_schema_for("chat:1234abcd-5678-90ef")
    assert s == "sp_chat_1234abcd"
    assert s.startswith("sp_chat_")
