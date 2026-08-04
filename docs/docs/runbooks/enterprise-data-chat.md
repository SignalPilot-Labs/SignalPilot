# Enterprise Data Chat Operations

Enterprise Data Chat capabilities default off outside the local Compose profile and
are independently controlled by `SP_FEATURE_CHAT_SANDBOX_RUNTIME`,
`SP_FEATURE_CHAT_QUERY_APPROVAL`, `SP_FEATURE_CHAT_STRUCTURED_RESULTS`,
`SP_FEATURE_CHAT_ORG_SHARING`, `SP_FEATURE_CHAT_FORKING`,
`SP_FEATURE_CHAT_SIZE_ROUTER`, `SP_FEATURE_CHAT_NOTEBOOK_ANALYSIS`,
`SP_FEATURE_CHAT_RUNTIME_RESULTS`, `SP_FEATURE_CHAT_RUNTIME_ARTIFACTS`, and
`SP_FEATURE_CHAT_DATASET_REFS`. Disable the affected flag and restart both gateway
and worker for immediate rollback. `SP_FEATURE_CHAT_SIZE_ROUTER=shadow` records route
decisions without enforcing them. Never enable DatasetRefs globally by default.

## Planner mismatch or unexpected route

1. Resolve the plan by opaque ID and compare SQL hash, run, user, project, commit,
   branch, connection, expiry, and policy hash. Do not paste SQL into tickets.
2. Join the plan to `gateway_governed_query_executions` and structured results to
   compare predicted scan/output rows and bytes with actual scan/output bytes, row
   count, cost, and duration.
3. Tune only the affected connector estimate adapter. Do not change the locked row
   or byte thresholds during shadow analysis.
4. Unknown estimates must remain 1,000-row scouting results until the analysis is
   rewritten as a bounded aggregate.

## Notebook or object-storage cleanup

1. A terminal run must have no active analysis kernel. Cancellation must reach the
   agent, active cell, SDK/warehouse query, and kernel.
2. New derived results, artifacts, and notebook archives live under the hashed
   organization and conversation prefix in the private chat-runtime bucket. Postgres
   contains references, hashes, sizes, provenance, and bounded previews only.
3. Expired DatasetRefs and partial multipart uploads must be absent after cleanup.
   DatasetRefs expire 24 hours after terminal run state.
4. Conversation deletion enqueues an idempotent prefix deletion. Retry pending rows;
   never delete an unverified broad prefix manually.
5. If object integrity validation fails, deny the download and quarantine the exact
   object key. Never fall back to a stale inline preview as if it were complete.

## Stuck query

1. Find the durable `gateway_governed_query_executions` row by run, execution, or
   warehouse query ID. Do not put SQL or result rows in operational tickets.
2. Call `POST /api/query/executions/{execution_id}/cancel` as the owning user.
3. Confirm the connector-native query is absent from the warehouse activity view.
4. If cancellation returns false, use the stored warehouse query ID with the
   warehouse administrator's native cancellation procedure.
5. Confirm the execution is terminal and the chat reservation was released or
   reconciled. A retry must create or reuse only the exact durable query proposal.

## Approval remains waiting

1. Check the proposal ID, SQL hash, estimated cost, owner, and status. Never copy
   normalized SQL into logs.
2. Confirm the conversation is `waiting_for_query_approval` and has no worker lease.
3. Confirm only one approval row exists for the proposal and user.
4. After 15 minutes the worker reaper should stop the sandbox and clear the runtime
   session ID. The durable run and proposal must remain waiting.
5. A later approval queues the same run. It is expected to provision a fresh sandbox
   and reconstruct context from gateway records.

## Sandbox startup or loss

1. Inspect the notebook-session row and pod events by opaque session/run ID.
2. In cloud mode, reject any sandbox pod without the configured gVisor RuntimeClass,
   non-root security context, read-only root filesystem, resource limits, and disabled
   service-account token.
3. Confirm the organization namespace default-deny and gateway egress policies exist.
4. Mark an unavailable session stopped; do not repair process-local Claude state.
5. Requeue the durable run. The next attempt must use the frozen project commit and a
   new Claude execution with no session resume.

## Estimator failure

An unavailable or low-quality estimate is not proof of zero cost. Keep the estimate
quality visible, require approval according to policy, and use connector-native dry
runs or plans where supported. DuckDB is the only certified zero-monetary-cost path.

## Track B failure

Abort the multipart upload, cancel the connector-native query, mark the execution
failed/cancelled, and remove partial objects. Unsupported connectors return
`aggregate_required`; they must never materialize all rows in gateway memory as a
fallback. Validate runtime memory, scratch disk, cancellation latency, and orphan
cleanup before enabling a connector.

## Security and privacy

- Operational logs may include opaque IDs, hashes, status, timings, row counts, and
  cost metadata. They must exclude questions, answers, SQL text, result rows,
  credentials, and artifact bodies.
- Shared links are authenticated, same-organization, hashed at rest, revocable, and
  read-only. Cross-organization and revoked lookups return not found.
- Treat a missing live connector certification as a deployment blocker, not a warning.
