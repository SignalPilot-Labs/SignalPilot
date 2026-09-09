# Cloud agent delegation over MCP

The existing `/mcp` endpoint can run a SignalPilot agent in a Docker container.
Codex and Claude Code use the same tools and cloud runtime. Agent execution is
enabled by default and requires the runtime configuration below.

Run the full FastAPI gateway application: its lifespan owns the background worker.
The standalone transport-only MCP entrypoint does not run the job worker.

## Enable

Apply gateway Alembic migrations through `0030`. Build the agent image from the
repository root:

```sh
docker build -f Dockerfile.agent -t signalpilot-agent:review .
```

Configure the gateway:

| Setting | Meaning |
| --- | --- |
| `SP_FEATURE_MCP_AGENT` | Defaults to `true`; set `false` to disable start and continuation |
| `SP_AGENT_IMAGE` | Built agent image; pin its digest in production |
| `SP_AGENT_DOCKER_SOCKET` | Docker Unix socket; defaults to `/var/run/docker.sock` |
| `SP_AGENT_DOCKER_NETWORK` | Dedicated Docker network for agent workloads |
| `SP_AGENT_MCP_URL` | Gateway `/mcp` URL reachable from that network |
| `SP_AGENT_MODEL` | Claude model supported by the configured organization key |
| `SP_RUNTIME_ENV` | Shared-database deployment isolation label; gateway replicas serving one queue must match |
| `SP_AGENT_MAX_CONCURRENT_PER_ORG` | Concurrent attempts per organization; defaults to 2, bounded to 1–20 |
| `SP_WORKSPACE_S3_*` | Existing workspace object storage configuration |

The gateway resolves the organization's existing Anthropic API key. The caller
needs an API key with `agent:run` scope. Existing keys do not acquire this scope
automatically. The selected project must already have a workspace revision and
the selected connection must belong to the caller's organization.

The gateway must have access to the configured Docker daemon. Docker access is
privileged operator infrastructure; the agent container never receives the
socket. Configure network egress at the deployment layer: a named Docker network
alone is not an outbound firewall. Permit the MCP gateway, workspace object
storage, model provider, and any explicitly required package hosts.

## Tool lifecycle

Start with `run_signalpilot_agent`:

```json
{
  "task": "Add freshness tests to my_orders",
  "project_id": "existing-project-id",
  "branch": "main",
  "revision": 3,
  "connection_name": "analytics_dev",
  "max_turns": 24,
  "timeout_seconds": 1200
}
```

Supply a unique optional `client_request_id` when starting a task. Reuse that ID
only to retry the same launch; retries return the existing thread without
starting another paid execution.

Start and continuation return a durable `queued` job promptly. The background
worker resolves model credentials and builds the snapshot after claiming the job.
No model credentials are persisted in the job record.

Call `wait_signalpilot_agent(thread_id, run_id, after_sequence=0, wait_seconds=20)`.
Each response contains ordered new activity, readable redacted SQL evidence,
elapsed time, `next_sequence`, and explicit `next_action` instructions. The outer
agent narrates useful evidence and waits again with `after_sequence=next_sequence`.
A wait returns immediately when activity arrives, or a heartbeat after at most 25
seconds. Ordinary MCP tool results provide visibility without another UI.

Continue until terminal status and `has_more=false`; terminal jobs can still have
activity pages to drain. Pages contain at most 50 events and approximately 12,000
serialized characters. Gateway query hooks publish authoritative execution events;
container activity is local progress and cannot forge query receipts. Terminal
results contain summaries, verification, changed paths, and expiring patch/snapshot
links. Changes remain artifacts rather than overwriting the managed workspace.

`input_required` is an application status in structured tool content. The outer
agent can ask the user its `question`, then call:

```json
{
  "thread_id": "returned-thread-id",
  "task": "Use received_at as the canonical timestamp"
}
```

with `continue_signalpilot_agent`. Continuation stages the previous output
snapshot and a bounded conversation history into a new container. It does not
depend on an MCP session or a persistent provider process.

`get_signalpilot_agent(thread_id)` returns status, activity, and renewed artifact
URLs. `cancel_signalpilot_agent(thread_id)` cancels queued or running work and
revokes nested MCP access. The runtime removes its container. Disconnecting or
cancelling a wait does not cancel the job. Status, wait, and cancellation work
across gateway replicas without the optional MCP Tasks extension.

Workers atomically claim queued jobs and renew a 45-second lease every 10 seconds.
Workers claim and reap only jobs with the same `SP_RUNTIME_ENV`. Unset labels match
only unset labels. Threads from another environment cannot be continued or mutated.
Queued jobs survive gateway restarts and expire after five minutes without a claim.
An orphaned running job fails after its lease expires and is never replayed because
its earlier work may already have executed. Start a new turn explicitly. Worker
shutdown stops its containers; deadlines and leases revoke credentials independently
of the client connection.

Threads can continue at most 12 attempts and remain accessible for seven days
from creation. This is an access deadline, not automatic data deletion. Configure
object-storage lifecycle cleanup for the `mcp-agents/` prefix and operational
cleanup of expired thread/event records according to the deployment's retention
policy.

## Execution boundaries

- Separate durable agent tables protect execution state from the public generic
  agent-run CRUD API. Ownership is checked by organization and user.
- Each attempt receives a signed credential bound to its active run, project,
  branch, and connection. It works only on MCP and a fixed set of governed
  query/schema REST adapters. Terminal/cancelled runs cannot reuse it.
- Agent control tools are hidden from in-app chat and delegated-agent catalogs.
  Direct calls from these identities are blocked even if their credential has
  `agent:run` and `admin` scopes. Eval identities cannot launch these agents.
- Data tools retain governed read/query access. The container has no warehouse
  write credential. Local `dbt parse` and DuckDB are available in the image;
  warehouse builds require an appropriate separately governed execution path.
- Input/output archives are bounded and path-validated. Links, special files,
  duplicate paths, and unsupported binary modifications are rejected.
- Source control internals, environment files, runtime config, dependencies,
  and generated dbt artifacts are excluded from returned source snapshots.
- Progress contains fixed observable phases, not raw transcripts or hidden
  reasoning. Execution credentials are not accepted in published source output.
- Container resource limits, an independent deadline, and automatic removal
  bound execution when the gateway disappears.

## SDK migration

The gateway uses MCP Python SDK 2.2.x, including `MCPServer` and its transport
factory options. Connector clients negotiate modern discovery and fall back to
legacy initialization. SDK-facing HTTP clients use `httpx2`; unrelated gateway
HTTP code continues using `httpx`. Protocol attributes use snake_case internally
and aliases when serializing wire JSON.

Deployment should smoke-test both target host versions against the actual
HTTPS proxy configuration. Host progress presentation and request timeouts
are client behavior; passing the protocol tests does not establish identical
Codex and Claude Code user interfaces.

## Review status

The implementation review passed 254 focused tests, including signed-token REST
authorization, modern/legacy MCP negotiation, pre-completion query evidence,
background job claims, cancellation isolation, bounded event pagination,
and an opt-in real Docker watchdog test. PostgreSQL 17 passed the MCP migration's
upgrade, downgrade, and re-upgrade before its merge renumbering to `0030` after
the dashboard chain ending at `0029`. Simultaneous PostgreSQL admissions
confirmed the organization concurrency limit. A separate Linux driver exercised
the complete Docker Engine API lifecycle with a fixture model response.

No paid model execution or deployed Codex/Cowork/Claude Code host smoke test was run.
Deployment validation still needs production networking, storage, credentials,
proxy timeouts, and an image pinned by digest. The broader
legacy fast/auth/server suites have pre-existing failures reproduced on the
fetched main baseline; the focused passing suite is not a claim that every
repository test passes.
