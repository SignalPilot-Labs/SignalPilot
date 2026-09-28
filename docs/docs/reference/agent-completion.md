---
title: Waiting for a delegated agent
---

`run_signalpilot_agent` returns immediately with `thread_id`, `run_id`, and a
chat link. The worker continues independently. The launch response does not
register an automatic notification that wakes the calling model.

To wait without receiving routine progress responses, call
`wait_signalpilot_agent`:

```json
{
  "thread_id": "<thread-id>",
  "run_id": "<run-id>",
  "mode": "completion"
}
```

Completion mode holds the request while the run is queued or running. It
ignores `wait_seconds`, forces summary detail, and returns the final result
and artifact metadata. Failures and cancellation also end the wait. A request
for clarification or approval returns `input_required` rather than waiting
forever for input the caller has not seen.

There is no server-side duration limit in completion mode. The host or proxy
can still time out or disconnect the request. Repeat the wait with the same
IDs if that happens. Do not launch a second agent. Disconnecting the wait does
not cancel the worker.

If the host supports background tool execution, run this wait in the background
to keep the calling agent available for other work. Returning a tool result
is not an unsolicited model notification; the host controls how it resumes
the calling agent.

The default `mode: "bounded"` preserves the existing wait of up to 25 seconds.
Use it when the host cannot maintain long-lived tool calls.

MCP defines optional [task support](https://modelcontextprotocol.io/extensions/tasks/overview)
for asynchronous results and notifications. This requires host capability
negotiation and a task lifecycle implementation; SignalPilot's queued launch
response is not itself an MCP protocol task.
