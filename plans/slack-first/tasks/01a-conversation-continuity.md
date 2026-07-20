# Task 1a — Conversation continuity (ship-today slice of Task 1)

**Parent:** [01-follow-up-conversations.md](01-follow-up-conversations.md) · **Status:** Proposed · **Scope:** gateway only — no engine changes, no orchestrator, no new infra

**User win:** SP stops feeling like a vending machine *today*: DM follow-ups keep context, plain thread replies continue the conversation, and a message sent mid-analysis gets an honest reply instead of dead air.

## What ships (3 features)

| # | Feature | User-visible behavior |
|---|---------|----------------------|
| F1 | DM continuity | DM: "what's our MRR?" → answer → "and per month?" → answered with full context. "reset" / "new analysis" starts fresh. |
| F2 | Thread replies without re-@mention | After SP answers in a channel thread, plain replies (no @SP) continue the conversation. |
| F3 | Honest busy state | Message during a running analysis → "still working on the previous question…" reply, never silence, never a duplicate pipeline. |

## Verified code facts (grounding)

- `_discussion_id` (worker.py:1287) = `slack:{team}:{channel}:{thread_ts}`; DM messages are unthreaded so `thread_ts` falls back to the message's own `ts` (worker.py:385) → **every DM message today = brand-new conversation**.
- Engine resume already works: `_ensure_record` (notion_analysis.py:1118) maps `discussion_id → record`, appends follow-up to the notebook when `status != "Analyzing"`, resumes the agent session. We only need to feed it a stable `discussion_id`.
- `request_id` is **deterministic**: `_analysis_request_id("slack", discussion_id)` = `slack-{uuid5(discussion_id)[:16]}` (gateway/notion/analysis.py:298). Any candidate `discussion_id` → computable `request_id` → trail lookup. No new state needed for existence checks.
- Gateway **analysis-trail store** is the durable conversation index: `AnalysisTrailInfo` has `request_id`, `source_thread_id` (= our discussion_id), `status: active|done|failed` (models/analysis_trails.py). Seeded before every run (worker.py:467), status updated on completion.
- **Constraint:** self-serve path builds a *fresh worker per event* (`_dispatch_self_serve_payload`, worker.py:1070-1116) → in-memory state does not survive between messages. All continuity/busy checks MUST go through the trail store (DB), not worker memory.
- Mid-run duplicate bug (bonus fix by F3): a second message in an active thread today spawns a full duplicate `_process_request` — duplicate progress reporter + duplicate poll on the same engine record.

## Design

### F1 — DM continuity

**Identity.** DM `discussion_id` = `slack:{team}:{channel}:dm-{epoch}` where `epoch` = `ts` of the first message of the conversation. Resolution on each DM message:

1. Query trail store for the **latest** trail whose `source_thread_id` starts with `slack:{team}:{channel}:dm-` → reuse its discussion_id (conversation continues).
2. No trail found, or message is a **reset command** → new epoch = this message's `ts`.

Requires one new store helper: `latest_trail_for_source_thread_prefix(db, org_id, prefix)` — single `LIKE prefix% ORDER BY created_at DESC LIMIT 1` query in `gateway/store/analysis_trails.py`.

**Reset command.** Exact-ish match (case/punctuation-insensitive) on: `reset`, `new analysis`, `start over`, `new conversation`. Reply confirming ("Fresh start — what do you want to look at?") when the reset message contains *only* the command; if it contains a question too ("reset — what's Q2 churn?"), rotate epoch and run the question.

**Context.** `_previous_thread_messages` (worker.py:763) uses `conversations.replies` keyed by `thread_ts` — useless for unthreaded DMs. Add DM branch: `conversations.history` on the channel, last 20 messages, same filtering (drop bot/self/subtypes). Matters mainly when the engine record is fresh but the DM has history (pod recycle).

**Reply placement (parity polish).** In DMs, reply in the main conversation (omit `thread_ts` on `post_message` / progress message) instead of threading every answer onto the question. Threads inside a DM are the #1 "this is a bot" tell.

**Plumbing.** `SlackRequest` gains `channel_type: str` (set from event at worker.py:371); `_discussion_id` and reply helpers branch on it.

### F2 — Thread replies without re-@mention

**Acceptance rule.** In `_request_from_payload`: accept `message` events where `channel_type != "im"` AND `thread_ts` present AND SP already owns that conversation — i.e. trail exists for `request_id = _analysis_request_id("slack", f"slack:{team}:{channel}:{thread_ts}")`. Top-level channel messages still require @mention. Existing guards stay: allowlist (worker.py:357), `bot_id`/subtype/self filters (worker.py:361-365).

Note: acceptance check needs a DB lookup inside `_request_from_payload`, which is currently sync-shaped but already async — fine. Dedupe stays first-line (`event_id`).

**App config (manual step).** Subscribe to `message.channels` (+ `message.groups` for private channels) in the Slack app event subscriptions. OAuth scope `channels:history` is already granted (used by `conversations.replies`); this is an event-subscription change, not a scope change — no reinstall prompt expected. Verify in dev workspace; if private-channel history scope is missing, F2 ships public-channels-only today.

**Noise guard.** For *continuation* messages (F2 accepts, or DM follow-up) that preflight classifies as non-`ANALYZE` ("thanks", "ok"): react 👍, post nothing. The canned "send me a specific data question" reply is only acceptable for fresh @mentions. This is a two-line branch in `_handle_preflight` using an `is_continuation` flag on `SlackRequest` — not the orchestrator (that's slice B).

### F3 — Honest busy state

Before starting the pipeline (in `_process_request`, before the progress message): compute `request_id` from the resolved `discussion_id`, fetch trail; if `status == "active"` →

> ⏳ Still working on the earlier question in this thread. Resend this after I post the result and I'll build on it.

…and stop. No progress message, no engine call, no duplicate poll.

**Race handling:** trail says `active` but run just finished (trail update lagging) → worst case the user is asked to resend; honest, acceptable. Trail stuck `active` after a crashed run would mute the thread — add a staleness escape: treat `active` trails with `updated_at` older than 30 min as not busy.

Queueing the message as an automatic follow-up after completion is **out of scope** (needs cross-process handoff; slice C territory).

## Touched files

| File | Change |
|------|--------|
| `gateway/gateway/slack_poc/worker.py` | `SlackRequest.channel_type` + `is_continuation`; DM discussion-id resolution + reset; F2 acceptance; DM history context; DM unthreaded replies; F3 busy gate; noise-guard branch in `_handle_preflight` |
| `gateway/gateway/store/analysis_trails.py` | `latest_trail_for_source_thread_prefix` helper |
| `gateway/tests/test_slack_poc_worker.py` | new tests (below) |
| Slack app manifest (dev + prod) | add `message.channels`, `message.groups` event subscriptions |

Engine (`notion_analysis.py`): untouched. Multi-client note: everything lands in the Slack adapter layer — conversation-identity mapping stays a client-adapter responsibility, which is exactly the contract we want for Notion later.

## Tests

- DM discussion-id: unthreaded DM → prefix id; existing trail → same id reused; reset command → new epoch; reset+question → new epoch and analysis runs.
- F2 acceptance matrix: thread reply with trail → accepted; without trail → ignored (no reply!); top-level channel message without mention → ignored; bot/self/subtype → ignored.
- F3: trail `active` → busy reply, no engine call; trail `done` → normal follow-up path; stale `active` (>30 min) → proceeds.
- Noise guard: continuation + non-ANALYZE preflight → reaction, no canned text; fresh mention + non-ANALYZE → canned text (unchanged).
- Store helper: prefix query returns latest by `created_at`.

## Definition of done

- [ ] Dev workspace, DM: question → answer → "and per month?" → contextual answer.
- [ ] Dev workspace, DM: "reset" → confirmation; next question has no stale context.
- [ ] Dev workspace, channel: @SP → answer → plain thread reply → contextual answer.
- [ ] Mid-run message in same thread → honest busy reply within seconds; no duplicate progress messages; original run delivers normally.
- [ ] "thanks" as a thread/DM follow-up → 👍 reaction only.
- [ ] Random thread reply in a thread SP never touched → SP stays silent.
- [ ] DM replies are unthreaded (main conversation).
- [ ] Unit tests above green; existing worker tests green.

## Risks / open decisions

- **Unbounded DM context:** one rolling conversation grows the agent session forever. Mitigated by reset command; auto-rotation (e.g. after N days idle) deferred.
- **`message.channels` event volume:** worker now receives every message in allowed channels; acceptance check must stay cheap (dedupe → filters → single indexed DB lookup) and silent on rejection.
- **Trail as conversation index:** we're leaning on `source_thread_id` + `status` semantics. If any path seeds trails without `source_thread_id`, DM prefix lookup misses — verify on the first manual test.
- **Self-serve vs. single-tenant socket worker:** both paths must behave identically; all new checks are DB-backed for that reason. Test in whichever mode the dev workspace runs, sanity-check the other before deploy.
