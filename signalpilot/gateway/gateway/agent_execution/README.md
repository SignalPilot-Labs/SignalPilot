# SignalPilot chat delegation over MCP

The existing `/mcp` endpoint is a launch and observation adapter for the same
agent used by Chats. MCP launches create real chat conversations and runs.
The existing chat worker owns authentication, model selection, sandbox startup,
execution, events, artifacts, cancellation, and cleanup.

Do not deploy a second MCP agent runtime. The independent Docker executor and
its `SP_AGENT_IMAGE`, `SP_AGENT_DOCKER_*`, `SP_AGENT_MCP_URL`, and `SP_AGENT_MODEL`
configuration are retired.

## Configuration

Run the gateway and existing chat worker with matching `SP_RUNTIME_ENV` labels
and the same notebook/sandbox configuration used by Chats. Staging's chat OAuth
override also applies to MCP launches. Production uses the same credential
resolution as Chats. No separate key, agent image, or sandbox is required.

`SP_FEATURE_MCP_AGENT` defaults to `true`. Callers need `agent:run` scope.
`SP_AGENT_MAX_CONCURRENT_PER_ORG` defaults to two and can only lower that limit.
Agent control tools remain unavailable to in-chat execution identities.

Select account defaults in **Settings → MCP Connect**. Start with only `task`.
Optional project, branch, and connection inputs remain subject to shared chat
authorization and readiness. The connection must match the project's configured
connection. Execution pins the same Git commit as Chats, not a separate workspace
snapshot or revision-materialization pipeline.

## Client experience

`run_signalpilot_agent` returns a conversation/run and its normal
`/chats/{conversation_id}` URL promptly. The user can watch the actual chat there.
Launch quietly. Do not continuously poll or narrate routine activity unless the
calling task requires the result or the user requests progress.

Call `wait_signalpilot_agent` with `thread_id`, `run_id`, and the previous
`next_sequence` as `after_sequence` only when an update is needed.
Each wait is bounded to 25 seconds. Summary detail is the default and excludes
repetitive deltas and large tool inputs/results. Disconnecting a wait does not cancel
the run. Use `cancel_signalpilot_agent` for explicit cancellation.

Summary waits batch activity until their deadline or a terminal/input-required
state. They do not return for each text chunk or tool event. On completion the
response contains the entire final assistant message without replaying the event
backlog. Read the full event history explicitly when it is useful.

`usage` contains recorded token counters. `cost_usd` is the runtime-reported model
cost, not a claim about the user's subscription charge. Missing accounting stays
absent rather than being reported as zero.

`continue_signalpilot_agent` uses the shared chat continuation lifecycle.
`get_signalpilot_agent` reads compact shared state and accepts the same cursor.
Use `detail="full"` only when the complete event payloads are needed.
`get_signalpilot_agent_event` reads one stored event by exact sequence and run ID.
`get_signalpilot_agent_context` pages through user/assistant chat messages using
`after_message_sequence`; it does not duplicate tool payloads in the transcript.
All substantive payloads appear once in MCP `structuredContent`. Text content
contains only status, the chat link, and a short next action.
All seven tools require `agent:run`, enforce ownership, and are hidden and blocked
for in-chat agents to prevent recursive delegation. Reading events/context does
not count as a governed query.
Reuse an optional `client_request_id`
when retrying a launch to avoid duplicate execution.

Errors pass through shared chat diagnostics, including original error details
with credentials redacted. Preserve truncation indicators when output is bounded.
Do not replace useful errors with generic failures or create a second event store.

## MCP SDK

The gateway uses MCP Python SDK 2.2.x. MCP-facing HTTP clients use `httpx2`;
unrelated gateway HTTP code uses `httpx`. Modern discovery and legacy
initialization remain supported. Host presentation and timeouts vary; test the
actual host and proxy as well as protocol-level behavior.
