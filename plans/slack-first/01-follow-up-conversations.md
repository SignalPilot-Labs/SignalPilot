# Task 1 — Conversations, not single shots

**User win:** Talking to SP feels like talking to Claude in Slack (Claude Tag): follow-ups work, you can steer or question a running analysis, "stop" stops it, and small talk doesn't trigger a data pipeline. SP behaves like a colleague, not a vending machine.

## Current behavior (why it feels single-shot)

The backend can resume: same `discussion_id` → existing record → follow-up appended, agent session resumed (`notion_analysis.py:1124-1134`). Three gaps break it in practice:

1. **DMs never resume.** `thread_ts` falls back to the message's own `ts` (`worker.py:373`); DM messages are unthreaded — every DM message = fresh `discussion_id` = fresh analysis, zero memory.
2. **Thread replies without @mention are ignored.** `_request_from_payload` only accepts `app_mention` or DM events.
3. **Messages during a running analysis are silently dropped.** `_ensure_record` only appends when `record.status != "Analyzing"` (`notion_analysis.py:1129`). No ack, no injection, no stop.

Additionally, the idle-time gate is a regex preflight (`analysis_delivery/preflight.py`) that refuses unusually-phrased legit questions with canned replies.

**Why the smart path is feasible:** the run loop already holds a live `ClaudeSDKClient` inside `async with` (`claude_agent.py:410`) and only calls `query()` once. The SDK supports additional `client.query()` calls into a running session (streaming input) and `client.interrupt()`. We just never exposed the client.

## Solution

### A. Conversation identity

- DM `discussion_id` = the DM channel (`slack:{team}:{channel}`), not message ts → a DM is one rolling conversation. Explicit "reset"/"new analysis" rotates an epoch suffix.
- Channel thread replies where SP was explicitly mentioned/invited are accepted without re-@mention. A durable thread-watch row covers pre-analysis replies; the analysis trail covers completed analysis follow-ups. Top-level channel messages still require @mention. Allowlist still applies. No new scopes needed.

### B. Orchestrator agent (generalizes the Notion follow-up planner; replaces the regex preflight)

Not a bare classifier — a lightweight agent **connected to the gateway MCP** (`/mcp`, same 40 tools the analysis agent uses). Fast model (Haiku), few turns, read-only tool budget. It sees the message + conversation state (idle/running, trace excerpt) and either **answers directly from tools** or **routes**:

| Intent | Idle | Analysis running |
|--------|------|------------------|
| `answerable` ("which DBs are connected?", "what tables do we have?", "how do we define ARR?", "did we run this before?") | **answer directly** via MCP tools (`list_database_connections`, `schema_overview`, `search_knowledge`, `query_history`, …) — seconds, no notebook | same — side path, main loop untouched |
| `analyze` (needs real data work) | start full notebook analysis | **inject** as steering if related to the running work; else tell user it's queued next and run after completion |
| `steer` ("use monthly", "exclude churned users") | treat as analyze/follow-up | **inject** into the live session |
| `question` about the run ("how's it going?", "why is confidence low?") | answer from last trace | answer from the live trace — main loop untouched |
| `control:stop` / `control:pause` | n/a | `interrupt()` the session, confirm in thread, keep partial results + trail link |
| `noise` ("ok", "thanks", emoji-ish) | 👍 reaction or nothing — **never** a canned refusal | same |

This creates a two-tier experience: metadata/knowledge questions answered in seconds by the orchestrator; only genuine analysis pays the minutes-long notebook cost. Everything in the system reachable via MCP is answerable at tier 1.

We are not starting from scratch on the routing shape: `plan_deliverable_followup` (`analysis_delivery/followups.py:32`, Notion-only) already produces a structured plan (mode + instructions + optional direct response). The orchestrator subsumes it and `classify_analysis_request`; both regex classifiers retire.

Guardrails: read-only MCP subset (no `query_database` at tier 1 initially — schema/knowledge/history tools only), hard turn cap, and when uncertain escalate to `analyze` rather than guess.

### C. Injection & control plumbing (notebook-server)

- Registry of live runs: `request_id → client handle` set inside the run loop when the client opens, cleared on exit.
- `POST /api/analysis/{request_id}/message` → `client.query(steering_text)` on the live session (framed as user steering: "User adds mid-analysis: …").
- `POST /api/analysis/{request_id}/interrupt` → `client.interrupt()`, mark record `Stopped`, flush partial output + notebook trail link to Slack.
- Gateway worker calls these instead of dropping mid-run messages.

### D. Graceful degradation

- Resume fails (pod recycled, `.chat_sessions.json` gone) → start fresh and say so ("my earlier working state expired — rerunning with your follow-up").
- Injection fails (run just finished) → run as normal follow-up instead.
- Orchestrator unavailable → conservative fallback: treat as `analyze` when idle, ack-and-run-after when busy. Never dead air.

### Ship order (thin slices, each demoable)

1. A — DM continuity + thread replies (biggest win, one small gateway-owned DB table)
2. B idle-side — orchestrator replaces regex preflight; tier-1 answers from MCP tools (kills canned refusals, adds instant answers)
3. C — stop/interrupt (safety valve users expect)
4. B busy-side + C injection — steer and question mid-run (the Claude Tag moment)

Out of scope: durable chat-session storage (accept warm-pod resume + D-fallback), channel-wide context, Block Kit buttons, pause-and-resume-later semantics (stop = stop; "pause" maps to stop with a friendlier confirmation).

## Definition of done

- [ ] DM: question → answer → plain "and per month?" → SP answers with previous context (manual, dev workspace).
- [ ] Channel: @SP → answer → plain thread reply follow-up (no mention) → SP answers.
- [ ] "Which databases are connected?" / "how do we define ARR?" answered in seconds from MCP tools, no notebook session spun.
- [ ] "How's it going?" mid-run gets a status answer within seconds; the analysis keeps running.
- [ ] "Actually use monthly numbers" mid-run visibly changes the running analysis (steering appears in the trail).
- [ ] "stop" mid-run halts within one turn, confirms, and links partial results.
- [ ] "thanks!" gets a reaction, never a canned "please be more specific."
- [ ] Both regex classifiers (`classify_analysis_request`, `plan_deliverable_followup`) retired; the orchestrator is the single gate for Slack, with Notion migrated or explicitly still on the legacy path.
- [ ] Resume failure and injection-race failure both produce honest messages, not confusion.
- [ ] Unit tests: DM `discussion_id` mapping, thread-reply acceptance, orchestrator intent → action matrix (mock LLM), interrupt endpoint, injection race (run finished between classify and inject).
