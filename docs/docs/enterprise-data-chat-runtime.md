# Enterprise Data Chat V1 Contracts

Contract version: `enterprise-data-chat-hybrid-v1`

This document fixes the persistence, authorization, security, and public-event
boundaries for the enterprise runtime. The executable Pydantic definitions live
in `signalpilot/gateway/gateway/standalone_chat/contracts.py`. Later phases may
add storage and behavior, but they must not weaken these invariants.

## Runtime and security boundary

The gateway owns durable state and is the sole authority for authorization,
query governance, budgets, approvals, results, and artifact access. A logical
run may use multiple physical sandboxes after recovery. A physical sandbox is
disposable and is never a durability boundary.

Each logical run gets one K8s pod at a time with the gVisor RuntimeClass in
cloud mode. It runs as non-root, has bounded CPU, memory, processes, and
ephemeral disk, and has no privileged mode, host mounts, Docker socket, cloud
metadata access, arbitrary egress, permanent database credentials, or GitHub
token. Its only writable location is run-scoped scratch space. Its only network
authority is a short-lived token scoped to the run, organization, user,
project, frozen commit, and connection at the SignalPilot gateway.

The gateway or project-sync service resolves and fetches the selected dbt
project. The sandbox sees an immutable checkout at the exact 40-character Git
commit recorded on first chat submission. Safe dbt inspection and compilation
are allowed. Repository writes, Git writes, `dbt run`, `build`, `seed`, and
`snapshot` are denied. Compiled analytical SQL executes only through the
gateway's governed query authority with a read-only database identity.

Operational logs may contain opaque IDs, timings, counts, states, and redacted
error classes. They must not contain questions, answers, SQL text, SQL result
rows, artifact bodies, credentials, or hidden model reasoning.

## Persistent query contracts

`QueryProposal` is the immutable approval unit. It binds normalized SQL and its
SHA-256 hash to organization, user, conversation, logical run, project, exact
commit, connection, execution path, timeout, policy version, purpose, and cost
estimate. SQL normalization rules are implemented by the governed executor in
Phase 1. Any SQL change creates a new hash, estimate, and proposal; an approval
for an older hash is invalid.

The proposal state machine is:

```text
proposed -> estimated -> approved -> executing -> completed
                         |              |          |
                         |              +--------> failed/cancelled
                         +-> waiting_for_approval -> approved/declined
```

`QueryExecution` identifies one idempotent warehouse attempt. It has a durable
execution ID before database work begins, records the warehouse query ID when
available, always has an explicit timeout, and links to one structured result
on success. Cancellation is idempotent and must attempt warehouse-side
cancellation even if the agent or sandbox is already gone.

`StructuredResult` is gateway-owned and authorization-scoped. It records typed
columns, warehouse row count when known, saved row count, a bounded preview,
three completeness dimensions, and provenance. The preview is context, not an
export and not proof of completeness.

New runtime results store at most 200 preview rows in Postgres. Full bounded SDK
results are private objects addressed only by gateway-owned references. Existing
bounded MCP results may remain inline. Object keys, storage credentials, and
presigned URLs are never part of an SDK or model-visible representation.

## Query planner and route contract

Every chat execution is bound to an expiring plan containing the normalized SQL
hash, run/user/project/commit/branch/connection scope, current policy hash, separate
scan and output estimates, estimate quality, route, reason, and approval decision.
Changing SQL, scope, connector policy, or routing policy invalidates the plan.

The locked Track A routes are:

- `mcp`: no Python is needed and predicted output is at most 10,000 rows and
  10 MiB.
- `notebook_sdk`: Python is needed, or output exceeds 10,000 rows, while staying
  at most 100,000 rows and 10 MiB.
- `aggregate_required`: output exceeds Track A and can be reduced in warehouse SQL.
- `refuse`: unsafe or unbounded work and raw export requests.

Scan size influences cost and approval, not execution location. Unknown output
estimates permit only a 1,000-row scouting result with unknown completeness. Set
`SP_FEATURE_CHAT_SIZE_ROUTER=shadow` to persist plans and measured outcomes without
enforcement; use `true` or `enforced` to enforce routes.

Track B adds `dataset_ref` only when its independent flag is enabled, the connector
supports batch streaming, and row-level runtime analysis is documented. It streams
redacted batches to private Parquet without list materialization. Dataset references
are opaque and expire 24 hours after the logical run becomes terminal.

## Disposable analysis notebook

The run scratch directory receives a seeded notebook before any kernel exists. A
kernel starts only through `start_analysis_notebook` after a valid
`notebook_sdk`/`dataset_ref` plan. The caller cannot supply a path. The kernel gets
only the short-lived run-scoped gateway identity and has notebook edit/run tools,
not Bash, package installation, arbitrary file tools, or web tools.

Notebook tool results redact the run token and bound structured previews before they
enter agent traces. Complete DataFrames and DatasetRefs stay in the kernel. Derived
results require source result IDs and a notebook code hash. Published files must be
regular scratch-relative files with valid extensions, MIME signatures, and size.

Before kernel shutdown, the runtime stores notebook source, a static HTML snapshot,
and a cell manifest in private object storage. The owner-only `View work` experience
loads the archived HTML in a sandboxed, no-network frame. Shares and forks exclude
notebook source, raw SQL, runtime traces, and runtime credentials.

Completeness has three independent meanings:

- Source completeness: whether the chosen sources, models, date range, and
  filters cover the business question.
- Result completeness: whether every row produced by the governed query was
  saved. Fetching `limit + 1` is the minimum proof for a row cap.
- Display completeness: whether a table or visualization displays every saved
  row, category, and series. Top-N, bucketing, and downsampling are display
  limits and must be disclosed even if the underlying result is complete.

Every dimension is `complete`, `truncated`, or `unknown`. `truncated` requires
a reason. Absence of proof is `unknown`, never `complete`.

Result provenance binds the query execution, SQL hash, project, exact commit,
connection, SignalPilot runtime version, plugin version, models, sources, and
freshness. Runtime and plugin versions are the versions actually used for that
physical execution, not the versions active when the conversation began.

## Budget and approval semantics

The default per-query automatic budget is USD 0.25. The default cumulative chat
automatic budget is USD 1.00. Values are non-negative decimal USD amounts; the
chat budget cannot be lower than the per-query budget.

Before execution, the estimated cost is transactionally reserved. A query
auto-runs only if its estimate is within the per-query budget and the reservation
fits the chat budget after actual spend and existing reservations. Concurrent
proposals lock the same chat ledger. A pre-execution failure releases the
reservation. Actual cost replaces the reservation when available; otherwise the
estimate remains the charged value. An actual overrun is recorded and disclosed.
There is no unapprovable monetary ceiling in V1.

The durable logical run enters `waiting_for_query_approval` whenever either
automatic threshold would be exceeded. This state releases the worker lease but
retains the proposal and reservation decision. The sandbox may stay warm for 15
minutes; approval after that window reconstructs the same logical run in a new
sandbox.

An approval binds the approver, exact SQL hash, connection, project, logical
run, approved estimate, policy version, and expiry. Its scope is exactly one of:

- `run_once`: authorize only this proposal; do not change either budget.
- `current_chat`: raise budgets for this conversation and its future proposals.
- `user_defaults`: authorize this proposal and explicitly store defaults for
  future chats; it does not retroactively change other chats.

Decline records durable context and authorizes no query or artifact. The agent
may narrow the query or explain why it cannot continue.

## Public query events

Public events are ordered by a per-run sequence and contain opaque identifiers,
safe progress metadata, costs, counts, and completeness. They never include SQL
rows, credentials, hidden reasoning, or unredacted failures.

- `query_proposed`: durable proposal exists.
- `query_estimated`: estimate and quality exist.
- `query_approval_requested`: automatic budget was exceeded.
- `query_approved`: an exact-hash approval was persisted.
- `query_declined`: the user declined the proposal.
- `query_started`: warehouse execution began.
- `query_progress`: safe elapsed time or connector progress changed.
- `query_completed`: result ID, costs, counts, and completeness are final.
- `query_cancelled`: cancellation is terminal for this attempt.

## Sharing contract

A share token is random and only its SHA-256 hash is stored. Resolution requires
authentication and the requester's organization must equal the owner's
organization; all other cases return not found. The owner alone creates or
revokes a grant. Archiving revokes access. A shared view is read-only and shows
only completed visible messages and completed artifacts. It hides partial
assistant output, prompts and controls, traces, SQL, provenance that exposes
private implementation state, and hidden reasoning. It follows newly completed
source-chat content until revoked.

## Fork contract

A fork is a recipient-owned conversation created from a completed shared-state
snapshot. The confirmation screen fixes the parent's project and exact commit,
shows editable recipient budgets and warehouse-cost notice, and requires an
explicit confirmation. Creation is atomic. It copies visible completed messages
and duplicates share-safe artifact objects under the fork's own prefix; it never copies process
memory, Claude sessions, credentials, tokens, leases, partial output, or hidden
reasoning.

The fork uses the same organization, project, and commit but the recipient's
ownership, scoped token, budgets, latest deployed runtime/plugin, fresh sandbox,
and live warehouse data for new queries. Parent and fork diverge permanently.
Later share revocation does not delete an existing fork.

## Feature boundaries

All enterprise phase flags are independent and disabled by default:

| Capability | Environment variable |
| --- | --- |
| Per-run sandbox runtime | `SP_FEATURE_CHAT_SANDBOX_RUNTIME` |
| Query estimates and approval | `SP_FEATURE_CHAT_QUERY_APPROVAL` |
| Structured results | `SP_FEATURE_CHAT_STRUCTURED_RESULTS` |
| Enterprise organization sharing | `SP_FEATURE_CHAT_ORG_SHARING` |
| Enterprise fork reconstruction | `SP_FEATURE_CHAT_FORKING` |
| Size-aware planner (`shadow` or enforced boolean) | `SP_FEATURE_CHAT_SIZE_ROUTER` |
| Lazy notebook analysis | `SP_FEATURE_CHAT_NOTEBOOK_ANALYSIS` |
| Object-backed runtime results | `SP_FEATURE_CHAT_RUNTIME_RESULTS` |
| Object-backed artifacts and archives | `SP_FEATURE_CHAT_RUNTIME_ARTIFACTS` |
| Track B streamed DatasetRefs | `SP_FEATURE_CHAT_DATASET_REFS` |

`SP_FEATURE_STANDALONE_CHAT` remains the outer product switch. These new flags
define later rollout seams and do not alter the already-shipped baseline until a
later phase wires a capability through its flag.
