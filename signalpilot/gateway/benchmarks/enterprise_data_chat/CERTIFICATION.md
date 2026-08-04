# Enterprise Data Chat Certification

Status on 2026-08-04: **NO-GO for enterprise enablement**.

Offline contract, policy, persistence, and DuckDB-compatible gold fixtures exist.
The deterministic scale generator produces exactly 100,000 customers, 2,000,000
orders, and 200,000 refunds; the validation build was 45,101,056 bytes.
The available local chat project targets the Nala warehouse with unrelated FX dbt
metadata, so it cannot execute the deterministic gold scenarios through the real
standalone-chat path. No connector is certified from mocks or static inspection.

Enterprise enablement requires recorded evidence for Postgres and at least one cloud
warehouse, followed by the remaining advertised connectors. For every connector,
record fixture version and size, gold-answer comparison, first progress and final
latency, sandbox/dbt/query timings, estimate versus actual cost, query count, scanned
rows or bytes, cancellation latency, worker/sandbox resources, artifact sizes, and
worker/sandbox recovery behavior.

Required gates include million-row aggregate/trend/top-N/join/funnel/cohort/anomaly
scenarios; raw-export refusal; per-query and cumulative approvals; delayed approval;
native cancellation; worker loss; four concurrent chats; artifact refinement; share
and fork; attempted database/project writes; and adversarial MCP-partial-row prompts.

Do not change this verdict to GO until live evidence proves that no answer silently
depends on truncation, expensive queries cannot bypass approval, cancellation stops
warehouse work, recovery does not duplicate costly execution, and connector safety
tests pass.

The hybrid planner, Track A bounded notebook runtime, private object-backed results
and artifacts, owner-only archived notebooks, and feature-gated Track B DatasetRef
path now have local contract tests. Those tests are implementation evidence only;
they do not certify live Kubernetes isolation, a real Postgres warehouse, Snowflake,
four-chat concurrency, worker/kernel loss, object-store failure, or business-answer
agreement. Track B remains disabled in the local Compose defaults.
