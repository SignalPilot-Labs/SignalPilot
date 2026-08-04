# Standalone Data Chat Baseline

Captured: 2026-07-31
Code revision: `9229042b`
Mode: static implementation characterization plus local service discovery. The
combined base+dev Compose stack was healthy, but its only ready chat project was
`test` on `nala-warehouse`, whose dbt metadata describes FX models rather than
the deterministic enterprise benchmark fixture.

## Current execution paths

| Property | MCP `query_database` | Standalone restricted Python / artifact path |
| --- | --- | --- |
| Authority | Gateway MCP query tool and existing SQL governance | Notebook runtime tool with gateway-scoped runtime claims |
| Result shape | Human-readable formatted text with bounded rows | Model-created table/chart/report snapshots |
| Mandatory estimate | No | No |
| Monetary approval | No | No |
| Explicit completeness | Inconsistent; a bounded response is not proof of completeness | Snapshot limits exist, but no source/result/display completeness contract |
| Durable structured result ID | No | No |
| Timeout | Connector/path dependent; not one mandatory contract | Agent stream has no single governed query timeout contract |
| Cancellation | Not uniformly bound to a durable warehouse query ID | Agent cancellation does not prove warehouse cancellation |

## Static baseline results

- Durable conversations, messages, logical runs, redacted public events, worker
  leases, recovery attempts, cancellation requests, and immutable artifacts
  already exist.
- The current run states are `queued`, `running`, `waiting_for_user`,
  `completed`, `failed`, and `cancelled`. There is no query-approval wait state.
- The standalone project context uses project and branch scope, but the
  conversation does not freeze an exact dbt commit.
- The runtime uses a Claude SDK client with a restricted standalone tool set.
  It receives dbt metadata, not a read-only checkout used for real dbt parse and
  compile operations.
- MCP may return a bounded formatted result. The model must not infer that the
  returned rows represent the full source.
- Artifact table snapshots cap saved rows at 1,000. Existing CSV is generated
  from that immutable snapshot and warns when its snapshot is truncated.
- Chart display caps categories and series independently of source rows. The
  chart sanitizer records display omissions, but there is no unified result
  completeness record shared by answer, CSV, chart, and report.
- Static HTML is sanitized, script-free, blocks remote resources, and receives
  a restrictive CSP. Sanitization can remove unsupported dynamic content.
- Artifact payloads are capped at 10 MiB.
- Same-organization authenticated sharing with hashed tokens is implemented.
  Shared responses omit private message metadata and provenance.
- The current fork copies a safe visible snapshot into recipient-owned records.
  It does not yet confirm frozen commit and budgets or reconstruct a fresh
  enterprise sandbox.

## Scenario status

The deterministic fixture and gold SQL are in `gold_questions.yaml`. The
following runtime baselines remain
`not_run`: full-history aggregate, monthly trend, high-cardinality top-N,
fanout-prone join, long-history anomaly, raw export policy, per-query and
cumulative approval, timeout, cancellation, worker loss, sandbox loss, and
cross-artifact consistency.

For each live baseline run, record: answer, SQL hash (not SQL in operational
logs), expected-result comparison, first-progress latency, final latency,
query duration, returned row count, truncation disclosure, failure code,
cancellation latency, and artifact hashes. Do not paste credentials, result
rows from customer data, questions, answers, or hidden reasoning into service
logs. Benchmark evidence belongs in a controlled test artifact.

## Known current failure modes

1. Bounded MCP rows or model previews can be described as complete without
   durable proof.
2. A query can execute without mandatory monetary estimation or approval.
3. Cancellation can stop agent work while warehouse work continues.
4. Recovery may retry without a durable warehouse execution identity.
5. Model-copied rows can make answers and artifacts disagree.
6. Chart category/series limits can omit meaningful values.
7. A branch can advance after chat creation because no exact commit is frozen.
8. Connector-specific timeout and estimate behavior is not normalized.

## Blocker

The local gateway, chat worker, notebook runtime, and sandbox were running and
healthy. However, the deterministic fixture is not loaded into the configured
`nala-warehouse` project and has no matching dbt project. Running an unrelated
starter question would not produce valid gold-answer or scenario latency
evidence. Phase 0 therefore remains incomplete until the fixture is exposed as
an authorized chat project and the listed scenarios are executed through both
MCP and SDK paths.
