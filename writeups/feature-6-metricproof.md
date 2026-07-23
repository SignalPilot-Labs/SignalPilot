# Feature 6 — MetricProof: Snowflake Semantic Views + Databricks Metric Views

**Status:** Built, hardened by 8+8 agent panel, 29 pure tests + docker tool-registration
verified. No live Snowflake/Databricks account — providers exercised via synthetic
outputs matching the documented formats (live validation is on the human task list).

## What was built

Roadmap item #14 / held idea #8: **read warehouse-native semantic layers and verify
agent-built models against them** — "we verify against YOUR semantic layer", the
partner-shaped play against Snowflake/Databricks instead of a war-shaped one.

### Components
- `gateway/semantic_layer/providers.py` — pure discovery/query construction:
  - **Snowflake Semantic Views**: `SHOW SEMANTIC VIEWS`, `DESCRIBE SEMANTIC VIEW`
    parsing (metrics with expressions/comments, dimensions), reference queries via the
    `SEMANTIC_VIEW(<view> METRICS … DIMENSIONS …)` table function. Logical-table-
    qualified names (`orders.total_revenue`) accepted — the documented GA form.
  - **Databricks Metric Views**: information_schema discovery, `DESCRIBE TABLE
    EXTENDED` METRIC_VIEW detection + tolerant YAML scrape of measures/dimensions
    (per-item properties like `comment:`/`format:`/`synonyms:` no longer truncate the
    section — panel catch), reference queries via `MEASURE(metric) … GROUP BY dims`.
  - Identifier validation on every user-supplied name.
- `gateway/semantic_layer/conformance.py` — the comparison engine:
  - Aligns groups on **normalized keys** (case/whitespace-insensitive strings,
    Decimal/float/int unification, midnight-datetime≡date, NaN sentinel).
  - Per-group statuses: match / drift / missing_in_model / missing_in_reference /
    non_numeric / **duplicate_in_model** (duplicate model keys = model not at grain =
    its own failure, never a silent overwrite).
  - Empty result sets are a **warn**, not a vacuous pass; NaN never launders to match;
    truncation past max_groups is flagged, not silent; `worst_rel_diff` is JSON-safe
    (infinite drift reported as a count, no `Infinity` literal).
- `gateway/mcp/tools/semantic_layer.py` — MCP tools `list_semantic_metrics` and
  `verify_metric_conformance` (registered; 54 tools total in docker).
  - **The free-text `where` parameter was removed** — panel flagged it as raw SQL
    through governance (critical) AND semantically wrong (pre-aggregation on
    Databricks, post-aggregation elsewhere). Scope with dimensions instead.
  - `tolerance_pct=0` now means exact agreement (was silently 0.5% via a falsy check).
  - Per-view describe failures surfaced in discovery output.

## Panel outcomes (16 agents, ~601k tokens)

Applied (of 63 findings): where-clause injection removal (critical), qualified
Snowflake names (critical — real Semantic View queries were impossible), YAML section
truncation, tolerance-zero falsy bug (flagged independently by 5 agents), Infinity
JSON, empty-result false pass, duplicate-key overwrite, NaN laundering, silent
truncation, Decimal/datetime key normalization, describe-failure visibility.

Backlog (best of ideation):
1. **Provider protocol + registry** decoupled from db_type — enables reference layers
   on separate endpoints. The enabling refactor for everything below. (high/medium)
2. **dbt Semantic Layer provider** (MetricFlow via Arrow Flight SQL) — biggest
   coverage win for the ICP. (high/large)
3. **Cube provider** — Postgres-wire, reuses the MEASURE() builder almost verbatim. (high/medium)
4. **LookML definition-level conformance** — file-based, no Looker account needed;
   catches count_distinct-vs-count and missing-filter classes at build time. (medium)
5. **OSI import/export** — "we speak OSI" positions MetricProof as the neutral
   verifier across the Snowflake/dbt/Salesforce consortium. (medium/small)
6. **PR-bot integration** — changed model ↔ semantic metric binding → conformance
   check as a PR comment (factor the tool body into a service function first). (high/medium)
7. **Metric-drift watches** — clone the schema_watch runner; alert on verdict
   transitions. (medium/medium)
8. Absolute-tolerance floor alongside relative; quoted-identifier support; block-scalar
   YAML `expr: >`.

## Verification
- 29 pure tests, all pass (providers, YAML, conformance math incl. the panel's cases).
- Docker: gateway boots, both tools registered.
- **Needs a human**: live validation against a real Snowflake account with Semantic
  Views and a Databricks workspace with Metric Views (see final human task list).
