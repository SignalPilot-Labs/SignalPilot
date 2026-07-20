# Task 1b - Agent + MCP intake routing for Slack and Notion

**Parent:** [01-follow-up-conversations.md](01-follow-up-conversations.md) - **Status:** Proposed - **Scope:** gateway-owned Slack + Notion intake routing through an internal agent/MCP loop; no notebook engine live injection/control yet; no new infrastructure.

**User win:** SP stops deciding by regex whether Slack or Notion should run analysis. A small intake agent gets tools, inspects the current conversation/product context, and chooses the next action: answer directly, react/ignore, start notebook analysis, update an existing notebook analysis, create an HTML deliverable, or update/refresh an existing Notion deliverable.

## Non-negotiable rule

No deterministic intent routing for whether Slack or Notion analysis is made.

Remove Slack/Notion runtime dependence on:

- `classify_analysis_request(...)`
- `wants_html_deliverable(...)`
- `plan_deliverable_followup(...)`
- greeting/thanks/ambiguous-data regexes
- keyword branches such as "dashboard means deliverable" or "revenue is ambiguous"

Code may still enforce operational constraints: auth, bot/self filtering, event dedupe, empty prompt handling, missing setup errors, structured tool-result validation, and the 01a active-run duplicate guard. Those checks do not decide user intent.

## Architecture

```text
Slack/Notion adapter
  -> build IntakeSession context
  -> run IntakeAgent with internal MCP tool allowlist
  -> agent calls read tools as needed
  -> agent must call exactly one terminal action tool
  -> adapter executes/continues from that terminal action result
```

The agent is not a JSON classifier with a prebuilt context blob. It is a tool-using intake agent. The tool schema is the contract; the model decides which tools to call.

Two tool classes:

- **Read tools:** safe context lookup. These help the agent answer tier-1 questions without spinning a notebook.
- **Terminal action tools:** exactly one final choice. These are the only way the agent can ask the adapter to do something externally visible.

If the agent does not call a terminal action tool, or calls more than one, the adapter posts a short operational failure and does not start analysis.

## Current code facts

- Slack fresh-message routing calls `classify_analysis_request(...)` in `gateway/gateway/slack_poc/worker.py::_handle_preflight`.
- Notion fresh-request routing calls `classify_analysis_request(...)` and `wants_html_deliverable(...)` in `gateway/gateway/notion/analysis.py::process_routed_comment_event`.
- Notion deliverable follow-ups call `plan_deliverable_followup(...)` in `gateway/gateway/notion/analysis.py::_process_deliverable_followup`.
- Notebook-server already has follow-up/update behavior: `signalpilot/_server/api/endpoints/notion_analysis.py::_ensure_record(...)` appends a follow-up cell when the same `discussion_id` record exists and is not `Analyzing`.
- Notebook-server already has an isolated refresh path: `POST /api/notion-analysis/refresh` writes a refresh notebook from captured base notebook code and runs it without resuming the original notebook.
- Existing MCP exports include context tools such as `list_database_connections`, `list_workspace_projects`, `schema_overview`, `schema_link`, `search_knowledge`, and `query_history`. Existing `run_notebook`, `manage_report`, and `manage_dashboard` are too broad for intake and should not be exposed to this agent in 01b.

## Deterministic routing audit

01b must cover every current deterministic flow that decides Slack/Notion user intent:

- Fresh Slack run-analysis preflight:
  - `gateway/gateway/slack_poc/worker.py::_handle_preflight`
  - `classify_analysis_request(...)`
  - `_GREETING_PATTERNS`, `_THANKS_PATTERNS`, `_CLEAR_ACTION_TERMS`, `_DATA_TERMS`, `_SPECIFICITY_TERMS`
  - canned direct/ambiguous responses such as "Send me a specific data question..."
- Fresh Notion run-analysis preflight:
  - `gateway/gateway/notion/analysis.py::process_routed_comment_event`
  - `classify_analysis_request(...)`
  - the same greeting/thanks/action/data/specificity regex and keyword sets
- Fresh Notion HTML deliverable detection:
  - `wants_html_deliverable(...)`
  - `_HTML_DELIVERABLE_PATTERNS`
  - `html_deliverable = wants_html_deliverable(prompt)`
  - `outputMode = "deliverable" if html_deliverable else "answer"`
- Existing Notion HTML deliverable follow-up planning:
  - `gateway/gateway/notion/analysis.py::_process_deliverable_followup`
  - `plan_deliverable_followup(...)`
  - `_REFRESH_RE`, `_EDIT_RE`, `_DIRECT_RE`
  - deterministic branches such as refresh-data vs edit-existing vs clarify

01b intentionally does not remove deterministic code that is not intake routing:

- notebook-server `outputMode` normalization and request validation
- HTML renderer tool parsing after a deliverable action has already been chosen
- HTML/CSS safety guards, size checks, class guards, and chart/layout post-processing
- auth, event dedupe, self/bot filtering, stale-run checks, and missing-resource errors

Audit command for the implementation PR:

```bash
rg -n "classify_analysis_request|wants_html_deliverable|plan_deliverable_followup|_HTML_DELIVERABLE_PATTERNS|_REFRESH_RE|_EDIT_RE|_DIRECT_RE|_GREETING_PATTERNS|_THANKS_PATTERNS|_CLEAR_ACTION_TERMS|_DATA_TERMS|_SPECIFICITY_TERMS|Send me a specific data question|dashboard means|revenue is ambiguous" signalpilot/gateway/gateway signalpilot/gateway/tests
```

Expected result: no Slack/Notion runtime imports or calls remain. Any surviving references must be dead-code deletion leftovers, test-only negative assertions, or explicitly documented non-intent renderer/validation code.

## What ships

| # | Feature | User-visible behavior |
|---|---------|----------------------|
| F1 | Internal intake agent with MCP tools | Slack and Notion route messages through one tool-using agent before choosing an action. |
| F2 | Read-only tier-1 answers | Questions like "which DBs are connected?", "what projects exist?", or "how do we define ARR?" can be answered from MCP context without notebook analysis. |
| F3 | Notebook action tools | The agent can start a new notebook analysis or update an existing completed analysis notebook as a follow-up. |
| F4 | Notion deliverable action tools | The agent can edit or refresh an existing Notion HTML deliverable without regex follow-up planning. |
| F5 | Old deterministic gates are dead | Tests fail if Slack/Notion routing reaches the retired regex/keyword classifiers. |

## Tool allowlist

### Read tools available in 01b

Use existing MCP tools where possible:

- `list_database_connections`
- `connection_health`
- `connector_capabilities`
- `list_workspace_projects`
- `schema_overview`
- `schema_link`
- `list_tables`
- `describe_table`
- `get_knowledge`
- `search_knowledge`
- `query_history`

Add internal intake read tools:

- `get_current_conversation`
  - Returns source, surface, prompt, previous messages, continuation state, source thread id, active/done analysis trail summary, and Notion deliverable summary when present.
- `get_analysis_status`
  - Returns status, trail URL, output mode, request id, notebook path, last updated time, and whether the record is currently safe to update.
- `get_analysis_trace_summary`
  - Returns a bounded sanitized trace summary for a prior Slack/Notion analysis. Use for "what did you do?", "why is confidence low?", and "what were you checking?".
- `get_deliverable_context`
  - Returns saved Notion deliverable metadata, report title/id, embed block availability, file upload availability, and whether refresh context exists.

### Terminal action tools

Add `gateway/gateway/analysis_delivery/intake_actions.py` or `gateway/gateway/mcp/tools/intake_actions.py` with internal-only tools:

- `respond_to_user(text: str)`
  - Adapter posts this to Slack/Notion.
- `react_or_ignore(mode: "react" | "ignore", reaction: str | None = None)`
  - Adapter reacts or stays silent. Default reaction for Slack continuation is `+1` only when the agent chooses `react` without a reaction.
- `start_notebook_analysis(prompt: str, output_mode: "answer" | "deliverable")`
  - Starts the existing notebook-backed analysis path for this Slack/Notion source thread.
- `update_notebook_analysis(prompt: str, output_mode: "answer" | "deliverable")`
  - Reuses the existing analysis record for the current source thread when safe. It calls the existing `/api/notion-analysis/start` path with the same `discussionId`, so notebook-server appends the follow-up cell through `_ensure_record(...)`.
  - If the analysis is still active and non-stale, return a terminal `busy` result instead of spawning duplicate work.
  - If no existing analysis record exists, return `not_found`; the agent should use `start_notebook_analysis` only if it explicitly wants a new analysis.
- `update_notion_deliverable(mode: "edit_existing" | "refresh_data", render_instruction: str, data_instruction: str | None = None)`
  - Wraps the existing `_process_deliverable_followup` execution paths. `refresh_data` calls the existing `/api/notion-analysis/refresh` flow with captured base notebook code. `edit_existing` uses the existing HTML follow-up renderer/replacement path.

Terminal action validation:

- The agent must call exactly one terminal action tool.
- `start_notebook_analysis` and `update_notebook_analysis` require `output_mode`.
- `update_notion_deliverable(refresh_data)` requires `data_instruction`.
- `respond_to_user` requires non-empty text.
- Tool validation failure is operational failure, not a fallback to analysis.

## Tools intentionally excluded from 01b

- `query_database`: intake should not do real data work. If answering requires live data, the agent should call `start_notebook_analysis` or `update_notebook_analysis`.
- `run_notebook`: too broad. The agent should use the notebook-analysis action tools, not arbitrary notebook execution.
- `manage_report` and `manage_dashboard`: too broad and admin-scoped. Notion deliverable updates should go through the purpose-built `update_notion_deliverable` action.
- write tools such as `propose_knowledge`, `archive_knowledge`, Notion page creation, schema mutation, branch tools, or report deletion.

## Agent contract

Add `gateway/gateway/analysis_delivery/intake_agent.py`.

The module owns:

- `IntakeSession`
- `IntakeToolCall`
- `IntakeTerminalAction`
- `IntakeAgent`
- `run_intake_agent(...)`

The agent gets:

- source: `slack` or `notion`
- surface: Slack DM, Slack thread, Slack mention, Notion comment, Notion deliverable follow-up
- prompt
- source thread id / discussion id
- previous messages
- active/done analysis trail hints
- available terminal actions for this surface
- tool allowlist

The agent must:

- Use read tools when it needs product/org context.
- Answer directly only from tool-provided or adapter-provided facts.
- Use `start_notebook_analysis` or `update_notebook_analysis` when real data work is needed.
- Use `update_notion_deliverable` when the user is asking to change or refresh a known Notion HTML deliverable.
- Use `react_or_ignore` for low-value acknowledgements or noise.
- Never rely on keywords/regexes outside the model/tool decision.

Model/runtime:

- Reuse the Anthropic Messages API pattern already used by `analysis_delivery/renderer.py` and `slack_poc/progress.py`.
- Resolve API keys through org secrets, not user-local env fallback.
- Add envs:
  - `SIGNALPILOT_INTAKE_MODEL`
  - `SIGNALPILOT_INTAKE_TIMEOUT_SECONDS`
  - `SIGNALPILOT_INTAKE_MAX_TOOL_CALLS`
- Temperature `0` is acceptable for stable tool use; the decision is still model-owned because no keyword/regex branch chooses intent.

## Implementation plan

### 1. Add internal MCP tool runner for intake

Files:

- `gateway/gateway/analysis_delivery/intake_agent.py`
- `gateway/gateway/analysis_delivery/intake_tools.py`
- `gateway/gateway/analysis_delivery/intake_actions.py`

Implementation notes:

- Prefer direct function calls to existing MCP tool functions under an intake-specific allowlist instead of exposing a public new endpoint.
- Set MCP context vars (`mcp_org_id_var`, `mcp_user_id_var`, scopes) before calling existing tool functions.
- Normalize tool outputs into short strings or JSON summaries to keep prompt size bounded.
- Keep full tool transcripts in logs/traces for debugging, but never log secrets.

### 2. Add analysis state/action helpers

Files:

- `gateway/gateway/analysis_delivery/intake_actions.py`
- `gateway/gateway/notion/analysis.py`
- `gateway/gateway/slack_poc/worker.py`
- `gateway/gateway/store/analysis_trails.py`

Add helpers that can:

- Resolve the current source thread to an existing `AnalysisTrailInfo`.
- Report whether an existing analysis is active, done, failed, stale, or safe to update.
- Start a new analysis using the existing Slack/Notion start paths.
- Update an existing analysis by reusing the same `discussionId` and calling the existing notebook `/api/notion-analysis/start` path.
- Return a typed terminal result: `posted`, `ignored`, `analysis_started`, `analysis_updated`, `deliverable_update_started`, `busy`, `not_found`, or `failed`.

### 3. Replace Slack preflight with intake agent

File: `gateway/gateway/slack_poc/worker.py`

- Replace `_handle_preflight(...)` with `_handle_intake(...)`.
- Run intake before `_process_request(...)`.
- For `start_notebook_analysis`, continue into the existing `_process_request(...)` path.
- For `update_notebook_analysis`, use the existing route/runtime but preserve the same `discussion_id`.
- For `respond_to_user`, post the agent text.
- For `react_or_ignore`, react or stay silent.
- Keep the 01a busy gate before notebook start/update. It prevents duplicate work; it does not classify intent.
- Remove routing fallback text such as "Send me a specific data question...".

### 4. Replace Notion fresh-request preflight with intake agent

File: `gateway/gateway/notion/analysis.py`

- Before request page creation, run intake.
- For `respond_to_user`, create a Notion comment and do not create a request page.
- For `react_or_ignore(ignore)`, return `processed` with no page.
- For `start_notebook_analysis`, create the request page and call the existing notebook analysis start flow.
- Set notebook `outputMode` from the terminal tool call, not from `wants_html_deliverable(...)`.
- Remove the `html_deliverable = wants_html_deliverable(prompt)` branch.

### 5. Replace Notion deliverable follow-up planner with intake agent

File: `gateway/gateway/notion/analysis.py`

- For existing deliverable comments, run intake with `surface=notion_deliverable_followup`.
- `update_notion_deliverable(edit_existing)` maps to the existing HTML render/replace path.
- `update_notion_deliverable(refresh_data)` maps to the existing isolated refresh path using `/api/notion-analysis/refresh`.
- Keep operational checks for missing report, missing embed block, missing file upload, and missing refresh context.
- Remove `plan_deliverable_followup(prompt)` from runtime routing.

### 6. Retire old exports and tests

Files:

- `gateway/gateway/analysis_delivery/__init__.py`
- `gateway/gateway/analysis_delivery/preflight.py`
- `gateway/gateway/analysis_delivery/followups.py`
- `gateway/tests/test_analysis_delivery.py`

Remove exports and tests for deterministic intake classifiers once no runtime path imports them. If unrelated tests still import them, update those tests to the new intake-agent/tool contract or delete the obsolete unit.

## Tests

- Unit: intake agent calls existing read tools under the allowlist and rejects non-allowlisted tools.
- Unit: intake agent requires exactly one terminal action tool.
- Unit: invalid terminal action args produce operational failure and do not start analysis.
- Unit: `update_notebook_analysis` returns `not_found` when there is no existing trail for the source thread.
- Unit: `update_notebook_analysis` returns `busy` for active non-stale analyses and does not call notebook start.
- Unit: `update_notebook_analysis` calls the existing notebook start path with the same `discussionId` for done/stale-safe analyses.
- Slack: mocked `respond_to_user` posts the agent response and does not call `_process_request`.
- Slack: mocked `start_notebook_analysis` reaches the existing analysis path even for text that old preflight would have called ambiguous.
- Slack: mocked `update_notebook_analysis` preserves `SlackRequest.discussion_id` and uses the existing analysis route.
- Slack: mocked `react_or_ignore(react)` on a continuation adds a reaction and posts nothing.
- Slack: monkeypatch `classify_analysis_request` to raise; Slack routing tests still pass.
- Notion fresh: mocked `respond_to_user` creates only a comment; no request page, no notebook call.
- Notion fresh: mocked `start_notebook_analysis(output_mode=deliverable)` sends `outputMode: deliverable`; no `wants_html_deliverable` call.
- Notion fresh: mocked `start_notebook_analysis(output_mode=answer)` and `start_notebook_analysis(output_mode=deliverable)` both work for prompts that would have matched the old HTML regex; output mode comes only from the terminal action.
- Notion deliverable: mocked `update_notion_deliverable(edit_existing)` reaches the existing replace path without `plan_deliverable_followup`.
- Notion deliverable: mocked `update_notion_deliverable(refresh_data)` reaches the existing `/api/notion-analysis/refresh` path.
- Notion: monkeypatch `classify_analysis_request`, `wants_html_deliverable`, and `plan_deliverable_followup` to raise; Notion routing tests still pass.

## Definition of done

- [ ] Slack and Notion runtime routing no longer import or call `classify_analysis_request(...)`.
- [ ] Notion fresh analysis no longer imports or calls `wants_html_deliverable(...)`.
- [ ] Notion deliverable follow-ups no longer import or call `plan_deliverable_followup(...)`.
- [ ] Intake routing uses an agent with MCP read tools plus terminal action tools.
- [ ] `update_notebook_analysis` exists and is covered by tests.
- [ ] The agent decision is the only path that chooses direct reply vs ignore/react vs start analysis vs update analysis vs HTML deliverable/update.
- [ ] Notebook `outputMode` is selected from the intake terminal action only, not from prompt keyword or regex matching.
- [ ] Tests prove the same prompt can lead to different actions depending on the agent tool calls.
- [ ] The deterministic routing audit command above has no surviving Slack/Notion runtime intent-routing references.
- [ ] Focused gateway tests pass:
  - `uv run pytest tests/test_intake_agent.py tests/test_slack_poc_worker.py tests/test_notion_analysis.py tests/test_analysis_delivery.py -q`
- [ ] `uv run ruff check gateway/analysis_delivery gateway/slack_poc gateway/notion tests/test_intake_agent.py tests/test_slack_poc_worker.py tests/test_notion_analysis.py`
- [ ] `git diff --check`

## Out of scope

- Live mid-analysis injection through `client.query(...)`.
- Stop/interrupt through `client.interrupt()`.
- Arbitrary database querying inside intake.
- Arbitrary notebook execution through `run_notebook`.
- Slack HTML deliverable generation.
- Reworking notebook analysis output contracts.

## Risks

- **Model unavailable:** do not silently fall back to deterministic analysis. Surface a short operational failure and stop.
- **Tool set too wide:** keep 01b allowlist narrow. Add tools only when they support routing or tier-1 answers.
- **Agent over-answers:** direct responses are only allowed from adapter context or read-tool output. If the answer requires live data, use notebook analysis.
- **Notebook update semantics:** updating a completed analysis relies on existing same-`discussionId` resume behavior. Test that it appends a follow-up cell and does not overwrite prior work.
- **Latency:** intake adds one model/tool loop before notebook startup. Bound tool calls and timeout; the payoff is avoiding multi-minute notebook runs when the agent can answer or ignore.
