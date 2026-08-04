"""Shape checks on the Postgres schema-introspection SQL.

Two failure modes these guard against, both found live on a Xata copy-on-write
branch where the schema looked empty while the tables held ~2M rows:

  1. Row counts read only pg_stat_user_tables.n_live_tup. That counter lives in
     the cumulative statistics collector, which is per-instance and starts empty
     on a cloned/restored server — so every table on a fresh branch reported
     0 rows. It reads identically to "the data never loaded".
  2. Managed Postgres hosts install pg_stat_statements into `public`. Those
     views were enumerated as user tables, so the real schema (one table) was
     outnumbered 2:1 by instrumentation.

The SQL is built inside PostgresConnector._get_schema_impl() as local strings,
so these assert on the generated text rather than executing it — a live-database
test would need a Postgres with a reset stats collector, which is exactly the
state that is hard to stage. The behaviour itself was verified against a real
Xata branch when the fix landed.
"""

from __future__ import annotations

import inspect
import re

import pytest

from gateway.connectors.drivers.postgres import PostgresConnector


@pytest.fixture(scope="module")
def get_schema_source() -> str:
    return inspect.getsource(PostgresConnector._get_schema_impl)


def _normalize(sql: str) -> str:
    """Collapse whitespace so assertions survive reformatting."""
    return re.sub(r"\s+", " ", sql)


# ─── 1. row counts must survive an empty statistics collector ────────────────


def test_row_count_falls_back_to_pg_class_reltuples(get_schema_source):
    sql = _normalize(get_schema_source)
    assert "reltuples" in sql, (
        "Row counts must fall back to pg_class.reltuples. n_live_tup alone reports 0 "
        "on any cloned/restored Postgres (e.g. a Xata copy-on-write branch)."
    )
    assert "JOIN pg_class c ON c.oid = s.relid" in sql, (
        "The fallback needs pg_class joined to pg_stat_user_tables on relid."
    )


def test_row_count_treats_zero_n_live_tup_as_unknown(get_schema_source):
    """COALESCE alone is not enough — n_live_tup is 0, not NULL, on a fresh
    clone, so it has to be NULLIF'd before the fallback can win."""
    sql = _normalize(get_schema_source)
    assert "NULLIF(s.n_live_tup, 0)" in sql


def test_row_count_treats_never_analyzed_reltuples_as_unknown(get_schema_source):
    """reltuples is -1 (PG14+) or 0 for a never-analyzed table. Neither may be
    reported as a real row count, and -1 must never reach the API."""
    sql = _normalize(get_schema_source)
    assert "GREATEST(c.reltuples, 0)" in sql, "negative reltuples must be clamped"
    assert "NULLIF(GREATEST(c.reltuples, 0)::bigint, 0)" in sql


def test_row_count_still_privilege_gated(get_schema_source):
    """The fallback must not become a way to read counts for unreadable tables."""
    sql = _normalize(get_schema_source)
    assert "has_table_privilege(s.relid, 'SELECT')" in sql


# ─── 2. extension instrumentation must not masquerade as user tables ─────────


def test_extension_owned_views_are_excluded(get_schema_source):
    sql = _normalize(get_schema_source)
    assert "pg_depend" in sql and "d.deptype = 'e'" in sql, (
        "Extension-owned views (pg_stat_statements et al) must be filtered via pg_depend."
    )


def test_extension_filter_is_scoped_to_views_not_tables(get_schema_source):
    """Extension-owned *tables* are often real reference data an analyst queries
    (PostGIS spatial_ref_sys). Only views/matviews may be hidden."""
    sql = _normalize(get_schema_source)
    m = re.search(
        r"AND NOT \(\s*c\.relkind IN \('v', 'm'\)\s*AND EXISTS \(\s*SELECT 1 FROM pg_depend",
        sql,
    )
    assert m, "the extension filter must be gated on relkind IN ('v','m')"


def test_extension_filter_matches_relations_only(get_schema_source):
    """pg_depend.objid is only unique per classid; without it this could match a
    dependency on an unrelated catalog object that happens to share an oid."""
    sql = _normalize(get_schema_source)
    assert "d.classid = 'pg_class'::regclass" in sql


# ─── 3. system schemas stay excluded ─────────────────────────────────────────


def test_system_schemas_remain_excluded(get_schema_source):
    sql = _normalize(get_schema_source)
    for frag in (
        "n.nspname NOT IN ('pg_catalog', 'information_schema')",
        "n.nspname NOT LIKE 'pg_toast%'",
        "n.nspname NOT LIKE 'pg_temp%'",
    ):
        assert frag in sql, f"missing system-schema exclusion: {frag}"
