# Feature Sprint 7-22 — Summary

Branch **`feature-sprint-7-22`** (off `eval-upload-system`), **not pushed**.
One commit per feature; the eval-upload WIP was committed first so every feature diff
is clean. 134 sprint tests green. Every feature was reviewed by an **8-ideation +
8-review agent panel** (≈5.7M subagent tokens across 8 panels + 4 sweep agents);
all critical/major findings were fixed *before* each commit.

| # | Feature | Commit | Proof |
|---|---|---|---|
| 1 | KB semantic search (3-arm RRF hybrid + retrieval logging + `read_knowledge` tool) | e129d5f0 | 30 tests; live docker: British-spelling semantic query ranks correctly; MCP events logged |
| 2 | KB retrieval heatmap (Insights view, staleness, per-source series) | 805d561d | 31 tests; live screenshots with real agent-retrieval data |
| 3 | PipelineProof GitHub PR bot (webhook + scan, comment upsert, commit status) | 539e6f49 | 22 tests; **live PR** on kiwi0401/sp-pipelineproof-test#1 — 3.48M-row model verified, ghost model failed |
| 4 | Schema-diff cron → GitHub PR (durable snapshots, deterministic branches, org-scoped tokens) | 023cc583 | 17 tests; **live PRs #2–#4** from real warehouse drift |
| 5 | Databricks parity (row-count backfill, EXPLAIN COST, sci-notation fix) | 877026ab | 19 mocked-cursor tests |
| 6 | MetricProof (Snowflake Semantic Views + Databricks Metric Views conformance) | ac1dcc83 | 29 tests; 2 new MCP tools registered (54 total) |
| 7 | dbt Fusion compat (probed the real 2.0.0-preview.202 binary in docker) | 12e0427e | 16 tests on captured fixtures; duckdb-supported + exit-code + v6-schema findings |
| 8 | UX overhaul (UX.md → tokens → sidebar IA → header → 4-agent page sweep) | ea8cd00a | tsc clean, docker build, 8 page screenshots |

Supporting commit: b2d70895 (FastAPI 204 strictness fix unblocking local test runs).

## What the panels caught (why they were worth it)
- A **syntax-broken module** masked by a hand-mirrored test (F7 runner.py).
- A **cross-org authorization hole** (schema watches could PR to another org's repo
  with that org's installation token).
- A **SQL injection vector** (MetricProof where-clause passthrough).
- A **Ctrl+C hijack** shipping bug in the new nav.
- A cost-estimator regex that made large Databricks queries look tiny (`5.43E+3` → 5).
- Systemic issues: unbounded retrieval-event growth, event-loop-blocking scans,
  duplicate-PR races, heatmap cold-flash, and ~40 more applied findings.

## Where everything lives
- Per-feature writeups + ideation backlogs: `writeups/feature-1…8-*.md`
- Panel details for F1: `writeups/feature-1-panels.md`
- **Your to-do list**: `writeups/HUMAN-TASKS.md` (GitHub App registration, embeddings
  provider key, Snowflake/Databricks live validation, Fusion benchmark time-mocking
  decision, UX click-through, scratch-repo cleanup).
- UX product doc: `signalpilot/web/UX.md`; screenshots `signalpilot/web/e2e-ux-*.png`.
