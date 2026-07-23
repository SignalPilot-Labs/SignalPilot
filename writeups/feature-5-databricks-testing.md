# Feature 5 — Databricks DB Testing & Parity

**Status:** Audited, gaps fixed, 19 mocked tests added, reviewed by 8+8 agent panel.
No live Databricks account — everything verified with high-fidelity cursor mocks
(fidelity cross-checked by a review agent against real databricks-sql-connector shapes).

## Audit result (vs the roadmap's "schema-tool parity gaps only")

The driver was more complete than the roadmap assumed (PAT/OAuth M2M/U2M auth,
information_schema introspection with PK/FK, Hive SHOW/DESCRIBE fallback, batched
sample values, `APPROX_COUNT_DISTINCT` dialect routing already wired). Real gaps found
and fixed:

1. **`row_count` was never populated** — DESCRIBE DETAIL has no rowCount, so every
   Databricks table reported 0 rows, starving grain/fan-out tooling. Added batched
   `COUNT(*)` backfill for small Delta tables (≤100 MB by DESCRIBE DETAIL size,
   UNION ALL batches of 20, 60s timeout, **runs in the connector thread pool** — not
   on the event loop), escaped identifiers/literals, per-batch failure isolation with
   debug logging. Tables with **NULL sizeInBytes (non-Delta/external) are excluded** —
   an unknown-size multi-TB Parquet table must never get scanned (panel catch: the
   `or 0` coercion previously let exactly those through).
2. **Cost estimator regression risk** — now tries `EXPLAIN COST` (has Statistics
   rowCount) before `EXPLAIN FORMATTED`, and parses **scientific-notation rowCount**
   (`5.43E+3`): Spark prints ≥1000-row estimates that way, and the old `\d+` regex
   truncated them to single digits — making big queries look tiny (panel's top find).
   Failure warnings now carry the underlying cause instead of "EXPLAIN not supported".
3. **DESCRIBE DETAIL now also captures** `partitionColumns`, `clusteringColumns`,
   `lastModified` (same call, zero extra round trips) — feeds full-scan warnings and
   stale-mart detection later.
4. Magic numbers hoisted to module constants (`_DETAIL_TABLE_CAP=50`,
   `_COUNT_SIZE_LIMIT_MB=100`, `_COUNT_BATCH=20`, `_COUNT_TIMEOUT_S=60`); dead
   `[:100]` cap removed (panel: it could never bind under the 50-table DETAIL cap).

## Tests (`tests/test_databricks_parity.py`, 19)

information_schema path (columns/types/views), PK/FK attach + failure tolerance,
DESCRIBE DETAIL metadata + extras, small-table backfill, large-table skip, NULL-size
skip, batch-failure isolation, Hive fallback, estimator COST→FORMATTED→warning chain,
scientific notation, conservative default, dialect routing, backtick quoting.

## Panel outcomes (16 agents, ~666k tokens)

Applied: scientific-notation regex (major), NULL-size scan hazard (major), event-loop
blocking COUNT batches (major), dead cap + constants, identifier escaping, batch-failure
logging, warning attribution, dead test scaffolding removed, estimator docstring.

Backlog (best of ideation):
1. **UC lineage system tables as inferred FKs** — ~95% of UC deployments declare zero
   FKs; `system.access.column_lineage` can backfill the join graph. (high/medium)
2. **DESCRIBE HISTORY operationMetrics for large-table row counts** — exact after a
   full overwrite, no scan. (medium/medium)
3. **Catalog-explicit introspection** (`system.information_schema` + table_catalog
   filter) — multi-catalog workspaces currently see only the session default. (high/medium)
4. **Move all introspection off the event loop** (whole `_get_schema_impl`, sample
   values, health checks — pre-existing pattern; COUNT batches now fixed). (high/small)
5. **session_configuration STATEMENT_TIMEOUT** at connect instead of per-query SET
   round trip. (medium/small)
6. **UC column masks / row filters** — flag masked columns so sample values aren't
   poisoned by redacted placeholders. (medium/small)
7. Parallelize DESCRIBE DETAIL (~5 concurrent). (medium)
8. `_get_schema_impl` split into named phase helpers (trino.py precedent). (refactor)
9. Live-test harness for when credentials arrive: Databricks Express/free-trial setup
   documented in the human task list; contract tests are mock-first by design.
