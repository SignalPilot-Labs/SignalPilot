# Feature 7 — dbt Fusion Integration & Testing

**Status:** Empirically tested against the real Fusion engine in docker;
compat fixes landed with tests. Roadmap item #24 ("dbt Fusion compat pass").

## Empirical probe (the interesting part)

Installed **dbt-fusion 2.0.0-preview.202** in a disposable Ubuntu container and ran it
against scratch projects. Findings — several contradict our own recon assumptions:

| Fact | Implication |
|---|---|
| `dbt --version` → `dbt-fusion 2.0.0-preview.202` (single line) | dbt-core version parsing (`installed:`/`Core:`) fails — **fixed** |
| **duckdb IS a supported adapter** (snowflake, bigquery, databricks, redshift, duckdb, salesforce, clickhouse) | The benchmark harness's dbt-duckdb setup is NOT blocked on Fusion, contrary to the audit's assumption |
| postgres adapter is **experimental** (`DBT_ALLOW_EXPERIMENTAL_ADAPTERS=true`) | dbt-proxy's postgres-only path needs the env var for Fusion users |
| Error format: `[error] [DependencyNotFound (dbt1048)]: …` + `--> models/broken.sql:1:15` | Lowercase markers with error codes; our `[ERROR]:`-anchored regexes never matched — **fixed** |
| Exit codes ARE nonzero on parse/run failure | returncode-based flows keep working |
| `run_results.json` keeps the v6 schema (`results[].status`) | ADE evaluator compatible as-is |
| Artifacts: `manifest.json`, `semantic_manifest.json`, no `partial_parse.msgpack` | workdir cleanup no-ops harmlessly |
| Section banners: `=== Errors and Warnings ===` / `=== Execution Summary ===` | parse-output structure differs but our line-based extraction copes |

## Fixes landed

- `gateway/dbt/validator.py` — warning/error marker regexes accept both engines:
  dbt-core `[WARNING]: …` (ANSI/timestamps) and Fusion `[error] [Name (dbtNNNN)]: …`.
- `notebook-server/…/_dbt/runner.py` — version detection handles the Fusion line,
  reporting `fusion-2.0.0-preview.202` so downstream can distinguish engines.
- `gateway/mcp/tools/dbt_project.py` (`dbt_error_parser`) — Fusion patterns: model
  from `Error in model X (path)`, error type from the `[error] [Name (dbtNNNN)]`
  marker, location from `--> file:line:col`, message extraction after the code
  bracket, and Fusion's "Table with name X does not exist" phrasing — regression-
  tested against the captured fixtures (model, dbt code, location, suggested fix).
- `gateway/dbt/error_parse.py` — the parser core extracted from the MCP tool into a
  pure module (testable without the MCP server); Fusion dbtNNNN codes surface in the
  error type, `-->` locations keep their file path, `LINE 5:` matches case-insensitively.
- `gateway/dbt/validator.py` degradation modes fixed for Fusion: the bare
  "profiles.yml" substring is gone (Fusion prints "Loading ~/.dbt/profiles.yml" on
  every run and misclassified all failures as profile_missing); Fusion parse-stage
  codes map to parse_failed.
- `notebook-server/…/_dbt/version_parse.py` — version parsing extracted into a
  dependency-free module; the gateway test suite loads and tests the REAL module by
  file path (no hand-copied mirror), plus a py_compile backstop on runner.py.
- `tests/test_fusion_compat.py` — 16 tests: REAL captured Fusion fixtures (parse
  error, run error, version line; the [warning] fixture is synthesized by analogy and
  labeled as such), dbt-core fixtures, degradation-mode regressions, and the full
  error-parser contract on both engines.

## Known remaining gaps (documented, not fixed here)

- **benchmark/Dockerfile.dbt-agent faketime shim**: LD_PRELOAD interception of a Rust
  binary is unreliable — the deterministic-time strategy needs rework before running
  the benchmark suite under Fusion (benchmark infra, outside gateway scope).
- dbt-proxy postgres-only restriction intersects with Fusion's experimental postgres
  adapter — works with the env var, unvalidated end-to-end.
- Fusion's stricter static analysis (rejects some dbt-core-tolerated Jinja) may flag
  agent-generated SQL that dbt-core accepted; the skills layer has no Fusion-specific
  guidance yet — candidate KB entry when real projects hit it.

## Panel outcomes (16 agents, ~675k tokens)
The panel caught a genuine critical: a comment edit had broken runner.py's syntax
(the module wouldn't import) while the hand-mirrored test stayed green — fixed by
extracting `version_parse.py` and testing the real module. Also applied: Fusion
profile_missing misclassification, uppercase-LINE location gap, file-path capture in
`-->` locations, error-parser extraction to a pure module with tests on the real
fixtures, fixture provenance corrections. Backlog: shared Fusion marker-regex module,
engine-detection helper with env override, `dbt compile` static-analysis validation
tier under Fusion, dbtNNNN code taxonomy → KB troubleshooting entries, Fusion adapter
preflight (auto-inject DBT_ALLOW_EXPERIMENTAL_ADAPTERS for postgres).
