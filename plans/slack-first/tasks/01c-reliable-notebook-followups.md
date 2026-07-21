# Task 1c - Reliable notebook follow-ups

**Parent:** [01-follow-up-conversations.md](01-follow-up-conversations.md) · **Status:** Proposed · **Scope:** Slack gateway + notebook-server analysis endpoint

**User win:** When a user asks "update this analysis", "try again", or "what changed?", SignalPilot reliably continues the same notebook context. If the old notebook cannot be reopened, SignalPilot gives a clear recovery message or reruns intentionally. Users never see raw notebook-server 404s.

## Why this exists

The 2026-07-21 Slack DM failure showed the current weak spot:

1. User asked: "can you update the results of that analysis?"
2. Intake selected the correct terminal action: `update_notebook_analysis`.
3. The Slack worker checked that an analysis trail existed and was safe to update.
4. The worker then treated execution like a fresh route resolution and generated a branch from the follow-up prompt.
5. Notebook-server tried to reuse the previous notebook path on the newly resolved branch.
6. The notebook file was missing on that branch, the async task crashed before the record was marked failed, and Slack surfaced a raw `404 Not Found` from `/api/notion-analysis/status/{request_id}`.

The important distinction: **intake chooses intent; the durable analysis trail must choose notebook identity.**

## Target behavior

- `update_notebook_analysis` always runs on the existing trail's `request_id`, `project_id`, `branch`, notebook path, runtime identity, and analysis user where available.
- A follow-up prompt can change instructions, not the notebook route.
- `start_notebook_analysis` can start a new analysis when there is no prior analysis or when the user explicitly asks for a fresh run.
- If an existing trail points to a missing notebook file, SignalPilot uses a controlled recovery path instead of leaking a raw 404.
- Notebook-server records failures durably, so polling returns `status: Failed` with a useful error body instead of `404`.

## Design

### 1. Preserve the existing analysis route for updates

Change Slack `update_notebook_analysis` handling from "status string only" to "status plus trail".

File targets:

| File | Change |
|------|--------|
| `signalpilot/gateway/gateway/slack_poc/worker.py` | Carry an update route/trail through `SlackRequest`; `_process_request` uses it instead of resolving a new branch from the follow-up prompt. |
| `signalpilot/gateway/gateway/analysis_delivery/intake_actions.py` | Reuse `IntakeAnalysisStatus.trail`; no new DB shape needed unless typing cleanup is useful. |
| `signalpilot/gateway/gateway/store/analysis_trails.py` | No new helper expected; existing `latest_trail_for_source_thread_id` already returns the needed row. |

Implementation shape:

- Replace `_notebook_update_status(...) -> str` with a helper returning `IntakeAnalysisStatus`.
- Add a small worker-local route override, for example:
  - `SlackRequest.analysis_route: notebook_analysis.AnalysisRoute | None`
  - or `SlackRequest.update_trail: AnalysisTrailInfo | None`
- When action is `update_notebook_analysis` and status is `safe_to_update`, build `AnalysisRoute` from the trail:
  - `source = "slack"`
  - `request_id = trail.request_id`
  - `project_id = trail.project_id`
  - `branch = trail.branch`
  - `default_branch = trail.default_branch or configured default`
  - `analysis_user_id = trail.analysis_user_id or f"analysis:slack:{trail.request_id}"`
- In `_process_request`, if a route override exists, skip `resolve_analysis_route_for_defaults(...)`.
- Keep `source_thread_id = _discussion_id(request)` so future Slack replies still find the thread.

### 2. Add route drift guardrails

Before calling notebook-server for an update:

- Verify the trail has `project_id`, `branch`, and `notebook_path`.
- Verify the route request id matches the current Slack discussion unless this is an explicit fresh run.
- If the trail is incomplete, post a controlled Slack message:

> I found the previous analysis, but its notebook route is incomplete. I can rerun it fresh from the thread context.

Do not fall back to a newly generated update branch silently.

### 3. Make notebook-server startup failures durable

In `signalpilot/notebook-server/signalpilot/_server/api/endpoints/notion_analysis.py`, `_run_analysis(...)` currently calls `_ensure_session(...)` before the broad failure handler.

Move `_ensure_session(...)` inside the guarded execution block, or add a narrow guard around it that:

- sets `record.status = "Failed"`;
- sets `record.error` to a concise, non-stacktrace message;
- saves the registry;
- appends a trace error event when possible;
- removes the request id from `_running_tasks`.

Polling `/api/notion-analysis/status/{request_id}` should return `200` with a failed status once `/start` accepted a request. A raw `404` should mean "this request id was never started on this route", not "the task crashed while starting".

### 4. Add missing-notebook recovery

For a safe update where the trail exists but notebook-server cannot reopen the notebook path:

Preferred recovery order:

1. Reopen from the existing branch and notebook path.
2. If the file is missing, restore/recreate from persisted completion artifacts if available.
3. If restore is not available, rerun from Slack previous messages plus the prior analysis trace summary, and explicitly tell the user this is a rerun.

Do not invent a new branch while claiming to update the old notebook.

### 5. Make "fresh analysis" explicit

The phrase "start fresh" should not accidentally reuse the same deterministic Slack discussion id.

Options:

- Add a terminal action `start_fresh_notebook_analysis`.
- Or add `fresh: true` to `start_notebook_analysis`.

For Slack:

- DMs can rotate the DM epoch to the current event timestamp.
- Channel threads can derive an analysis discussion id with a run suffix, for example `slack:{team}:{channel}:{thread_ts}:run-{event_ts}`.
- The visible Slack thread remains the same, but the notebook identity is new.

This should be a separate commit from the update-route fix because it changes product semantics.

### 6. Improve observability

Log these fields at the action handoff:

- terminal action name;
- `source_thread_id`;
- selected `request_id`;
- selected `project_id`;
- selected `branch`;
- whether route came from `existing_trail` or `fresh_resolution`;
- notebook path for updates.

This makes future failures answerable from logs without reconstructing state manually.

## Suggested commit sequence

1. **Slack update route reuse**
   - Carry the existing trail through `update_notebook_analysis`.
   - Use trail route in `_process_request`.
   - Add regression tests for branch preservation.

2. **Notebook-server durable startup failure**
   - Guard `_ensure_session`.
   - Return failed status instead of raw 404 after accepted starts.
   - Add tests for missing notebook path.

3. **Missing-notebook recovery**
   - Add controlled recovery/fallback behavior.
   - Add Slack-facing message tests.

4. **Explicit fresh analysis**
   - Add `fresh` action semantics.
   - Rotate analysis discussion id intentionally.
   - Add tests for DM and channel-thread fresh starts.

5. **Observability polish**
   - Add route/source logs.
   - Keep log fields non-sensitive.

## Test plan

- Slack worker: existing trail on branch A, follow-up prompt would generate branch B, intake chooses `update_notebook_analysis`, worker still calls notebook-server with branch A.
- Slack worker: `update_notebook_analysis` with no trail posts "no earlier analysis" and does not start notebook work.
- Slack worker: incomplete trail posts controlled recovery message and does not silently fresh-route.
- Notebook-server: accepted `/start` request whose session creation fails returns `status: Failed` on `/status/{request_id}`.
- Notebook-server: missing notebook path produces a concise record error, not an unhandled task exception.
- Intake integration: "update the results", "rerun with latest data", and "what changed since last time?" map to update when a safe trail exists.
- Fresh semantics: "start fresh" creates a new notebook identity instead of reusing the prior deterministic request id.

## Definition of done

- The original 404 scenario becomes either a successful same-notebook update or a controlled recovery message.
- Follow-up updates never derive a new branch from the follow-up prompt.
- Slack never displays raw notebook-server HTTP exceptions for accepted analysis starts.
- Tests prove update route preservation, startup failure durability, missing-notebook recovery, and explicit fresh-start behavior.
