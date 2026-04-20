# SignalPilot Benchmark Agent — Continuation Prompt

You are picking up work on the **SignalPilot dbt agent** project. Your goal is to
improve the agent's pass rate on the Spider2-DBT benchmark (currently **29/65 = 44.6%**,
target is to beat Databao's 44.11% and climb), **but the real goal is to build the
best general-purpose dbt agent possible**. The benchmark is a proxy, not the product.

This document is your orientation. Read it start-to-finish before touching anything.

---

## 0. Posture and principles (non-negotiable)

Before any decision, re-read this list. Many mistakes in this project came from
violating one of these.

### 0.1 The product is "Best DBT Agent", not "Best Spider2 Submitter"
Every change you make should produce a **better agent for any real dbt project**.
If a change only helps Spider2 tasks and would make production use worse, reject
it. If you can't tell whether a change is benchmark-specific, assume it is and
think harder.

**Red flag**: you're hardcoding task names, embedding known table names in the
prompt, reading from the gold DB, or writing SQL that only makes sense for
Spider2's particular scaffold choices. Stop.

### 0.2 Never leak gold data into the agent's context
The gold DuckDB files at `spider2-repo/spider2-dbt/evaluation_suite/gold/<task>/`
are **evaluation-only**. The agent must never:
- See their content, schema, or row counts
- Have them referenced in its prompt or tools
- Have their paths passed to any MCP tool or script the agent calls
- Be told anything the gold reveals that the raw scaffold doesn't

If you catch yourself writing "for task X the expected row count is Y", stop.
That's overfitting and it makes the benchmark meaningless.

### 0.3 Never overfit the prompt or skills to specific tasks
- No task name in the main prompt
- No column name from any specific gold
- No "if task is synthea001 then..." branches anywhere
- Skills describe **general dbt patterns**, not Spider2 quirks
- If your fix helps exactly one task and would be confusing in a real dbt context,
  you are overfitting

### 0.4 Keep the main system prompt slim
The main system prompt (`benchmark/prompts/dbt_local_system.md`) should contain:
- The task statement placeholder
- Core workflow shape (Steps 0-5)
- Tool pointers and short descriptions
- Top-level safety rules (don't overwrite source tables, etc.)

It should **not** contain:
- Specific SQL patterns (those live in skills)
- Task-specific hints
- Long prose explaining edge cases
- Walls of example code

**Rule of thumb**: if a section is useful only for a specific pattern (date spines,
ROW_NUMBER tiebreakers, surrogate-key generation), it belongs in a skill under
`benchmark/skills/`, not in the main prompt.

### 0.5 Use the Skill tool for domain knowledge
Skills live in `benchmark/skills/<name>/SKILL.md` and are loaded on-demand by the
agent via the built-in `Skill` tool. The current skills are:
- `dbt-workflow` — general dbt project workflow
- `dbt-verification` — post-build verification
- `dbt-debugging` — error triage and recovery
- `duckdb-sql` — DuckDB-specific SQL patterns

When you notice a recurring problem across several failing tasks, create or
update a skill. When you notice the prompt growing, move a section into a skill.

### 0.6 Research before implementing
Before adding a new MCP tool, a new skill, or a prompt change, spend ~10 minutes
looking at what the wider dbt + agent community has published recently:
- Check dbt's docs for recent features (exposures, unit tests, model contracts,
  model governance, dbt Fusion engine capabilities)
- Search for "dbt agent" blog posts and papers (things like Databao's approach)
- Look at recent Anthropic / OpenAI writings on coding agent patterns
- Check MCP servers for new dbt-adjacent tools you could borrow ideas from

You have `WebSearch` and `WebFetch`. Use them. Prior research is cheaper than
reimplementing something someone already got right.

### 0.7 Run only 1-3 tasks when iterating
Full 65-task sweeps take **hours** and cost real money. Use them only for:
- Milestone verification (before updating the score in `progress.md`)
- Regression checks after a large refactor
- Formal comparisons against a previous baseline

For **iterative development**, run 1-3 representative tasks per attempt:
- Pick 1 task that exhibits the failure you're fixing
- Pick 1 task that was passing (regression check)
- Optionally a third task from a different category (generalization check)

If those three work, THEN consider a wider sweep.

### 0.8 Validate for the right reason, not just the score
When a task flips from FAIL to PASS, don't assume you fixed it. Verify:
- Read the turn-by-turn trace. Did the agent actually apply the intended fix,
  or did it pass for a different reason?
- If the change is supposed to cut exploration turns, did it?
- If the change is supposed to trigger a specific MCP tool, did the agent use it?
- If the change is supposed to prevent a failure mode, run a task where that
  failure mode was obvious and confirm the fix activates

A "lucky pass" that doesn't come from the intended mechanism is a regression
waiting to happen.

### 0.9 Never modify the gold, eval config, or task jsonl
There's one documented exception (chinook001 eval config had `fct_invoice` where
both the gold and the correct output use `fact_invoice` — a typo in Spider2's
file). Patches to the eval config are acceptable **only** when:
- You can prove with a script that the current eval config references a name
  that exists in neither the gold DB nor any valid output
- You patch only the specific broken entry
- You keep a `.bak` of the original
- You document the change in `docs/runs.md`

Any other "gold rewriting" is forbidden. See `non-determinism-investigation.md`
for a full walkthrough of why.

### 0.10 Write down what you learn
Update `docs/progress.md` and `docs/runs.md` after any meaningful discovery.
Create new docs under `docs/` for deep-dives (see `non-determinism-investigation.md`
as a template). Future sessions should be able to re-enter without re-learning.

---

## 0.11 Pre-flight checklist — RUN THIS EVERY SESSION BEFORE ANY REAL WORK

**Why this exists**: Half the debugging time on this project came from silent
infrastructure failures (MCP not connecting, skills not loading, tools not
exposed) that produced "normal-looking" failed runs. The agent would waste
20+ turns flailing on `ToolSearch` because the tools it was told to use
literally didn't exist in its toolset, and we'd interpret the bad result as
"the agent is dumb" when the real answer was "nothing was wired up".

Run **every one** of these checks before you trust any benchmark output.
Each check has:
- what to run
- exactly what you should see when it's working
- exactly what you'll see when it's broken
- how to fix it

If any check fails, STOP and fix it before running any task. Do not skip.

---

### ✅ Check 1 — Gateway HTTP is alive on port 3300

**Run:**
```bash
curl -s --max-time 3 http://localhost:3300/api/connections
```

**Working**: returns a JSON list (may be empty `[]` or contain prior test connections).

**Broken**: connection refused, empty response, or timeout. You'll see
something like `curl: (7) Failed to connect to localhost port 3300`.

**Fix**: start the gateway:
```bash
cd signalpilot && docker compose -f docker/docker-compose.dev.yml up -d
```
Wait ~5 seconds, re-run the curl.

---

### ✅ Check 2 — dbt is installed and on PATH

**Run:**
```bash
which dbt && dbt --version
```

**Working**: prints a path and shows dbt-core 1.x + dbt-duckdb 1.x. Example:
```
/usr/local/bin/dbt
Core:
  - installed: 1.11.7
  ...
Plugins:
  - duckdb: 1.10.1 - Up to date!
```

**Broken**: `command not found` or wrong version.

**Fix**: activate the correct conda env. The main env is `SignalPilot`. Never
use the `sp-spider2-eval` env for normal work — it has pinned older versions
for the non-determinism investigation only.

---

### ✅ Check 3 — Unit tests for the dbt MCP subpackage pass

**Run:**
```bash
python -m pytest tests/test_dbt_project_map.py --tb=short
```

**Working**: `43 passed in ~1.5s`.

**Broken**: any failure in the 43 tests.

**Fix**: don't proceed. The test failure tells you what's wrong in the MCP
subpackage. Fix it before touching anything else.

---

### ✅ Check 4 — MCP server SDK-path handshake succeeds

**This is the single most important check.** If it fails, the agent will
ignore every `mcp__signalpilot__*` tool reference in the prompt and waste
turns on ToolSearch.

**Run:**
```bash
python benchmark/_verify_mcp_sdk.py 2>&1 | head -50
```

**Working**: the `SystemMessage init` line (message #1) must contain BOTH of these:
```
'mcp_servers': [
    ...
    {'name': 'signalpilot', 'status': 'connected'}
]
```
AND the `tools` list must contain MCP tools, specifically:
```
'tools': [..., 'mcp__signalpilot__dbt_project_map',
                'mcp__signalpilot__dbt_project_validate',
                'mcp__signalpilot__schema_link',
                'mcp__signalpilot__query_database', ...]
```

You should also see the full roundtrip end with the agent actually invoking
`mcp__signalpilot__dbt_project_map` and getting back real content like
`# Work order for chinook ...`. The final `ResultMessage` should have
`is_error: False`.

**Broken — mode A: `status: failed`**
```
'mcp_servers': [
    {'name': 'next-devtools', 'status': 'connected'},
    {'name': 'signalpilot', 'status': 'failed'}
]
```
AND the `tools` list has NO `mcp__signalpilot__*` entries. Downstream, the
agent will make repeated `ToolSearch(select:mcp__signalpilot__...)` calls,
each returning `No matching deferred tools found`, then eventually declare
"the SignalPilot MCP server is not currently connected".

**Fix**: the subprocess that spawns the gateway MCP is failing silently.
Common causes in this project's history:
1. **PYTHONPATH not injected** — Claude Code CLI strips `cwd` from the MCP
   config, so the gateway subprocess can't find the `gateway` package. Check
   `benchmark/run_dbt_local.py` around line 237; the `mcp_config` must inject
   `PYTHONPATH=str(GATEWAY_SRC) + os.pathsep + os.environ.get('PYTHONPATH','')`
   AND merge `os.environ` (not replace it) in the `env` dict.
2. **Windows `fcntl` import crash** — `signalpilot/gateway/gateway/store.py`
   must have the conditional `try: import fcntl / except ImportError: <shim>`
   block at the top. If someone removed it, put it back.
3. **Gateway not running** — see Check 1. The MCP server proxies to the
   gateway HTTP API, so the gateway must be alive.

Run the diagnostic the same way the runner spawns MCP:
```bash
python benchmark/scratch/_verify_mcp.py  # direct stdio_client test
```
If the direct test passes but `_verify_mcp_sdk.py` fails, the problem is in
how `run_dbt_local.py` builds the MCP config.

**Broken — mode B: `tools` list missing expected entries**

Tools list has `mcp__signalpilot__dbt_project_map` but NOT
`mcp__signalpilot__dbt_project_validate`, or vice versa. Means the MCP server
is running an old version of `mcp_server.py` that doesn't register the newer
tools.

**Fix**: confirm `signalpilot/gateway/gateway/mcp_server.py` has both
`@mcp.tool()` decorators for `dbt_project_map` and `dbt_project_validate`.
If this file was edited, the MCP subprocess picks up the change automatically
on next spawn.

---

### ✅ Check 5 — Claude Code CLI can spawn the agent at all

**This catches the Windows `CreateProcess` command-line-length bug.** If the
prompt gets too long, `claude.exe` fails to launch with a misleading
`CLINotFoundError`.

**Run**: execute Check 4 above (`_verify_mcp_sdk.py`). If it gets past the
`SystemMessage init` phase and emits at least one `AssistantMessage`, you're
good.

**Broken**: the SDK error looks like
```
CLINotFoundError: Claude Code not found at:
    C:\Users\...\claude_agent_sdk\_bundled\claude.exe
```
Even though the file exists. Underlying cause:
```
FileNotFoundError: [WinError 206] The filename or extension is too long
```
Meaning the command line passed to `CreateProcess` exceeded ~32767 chars,
typically because the system prompt was inlined as an argv.

**Fix**: check `benchmark/run_dbt_local.py` writes the system prompt to
`_system_prompt.md` and passes it as a dict:
```python
system_prompt_arg: dict = {"type": "file", "path": str(system_prompt_path)}
...
options = ClaudeAgentOptions(
    system_prompt=system_prompt_arg,
    ...
)
```
Not as a raw string. This routes through `--system-prompt-file` instead of
`--system-prompt`, bypassing the argv length limit.

---

### ✅ Check 6 — Skills are on disk in the workdir after setup

This is not the same as "skills are loaded by the agent". This just confirms
the files exist. Agent loading is Check 8.

**Run** (after starting a run or running `prepare_test_env`):
```bash
ls benchmark/test-env/<task>/.claude/skills/
```

**Working**: four directories, each containing `SKILL.md`:
```
dbt-debugging/
dbt-verification/
dbt-workflow/
duckdb-sql/
```
And:
```bash
find benchmark/test-env/<task>/.claude/skills -name SKILL.md | wc -l
```
should print `4`.

**Broken**: directory missing, or fewer than 4 SKILL.md files.

**Fix**: check `benchmark/skills/` (the source) has four skill directories.
If yes, the copy step in `prepare_test_env` (`run_dbt_local.py:107-112`) is
broken — check it exists and runs. If no, the source skills got deleted.

---

### ✅ Check 7 — System prompt actually renders the MCP tools

**Run**: after a run starts (or manually call `build_system_prompt`):
```bash
grep -c "mcp__signalpilot__dbt_project_map" benchmark/test-env/<task>/_system_prompt.md
grep -c "mcp__signalpilot__dbt_project_validate" benchmark/test-env/<task>/_system_prompt.md
grep -c "Skill tool" benchmark/test-env/<task>/_system_prompt.md
```

**Working**: first two return ≥1. Third may return 0 (not explicitly
referenced by name) but that's OK.

**Broken**: zero references. Means the prompt template was rolled back or
the `build_system_prompt` function is rendering an old version.

**Fix**: confirm `benchmark/prompts/dbt_local_system.md` has the
`## DBT Project Discovery` section listing both tools, and that
`build_system_prompt` in `run_dbt_local.py` uses `_load_prompt("dbt_local_system", ...)`.

---

### ✅ Check 8 — Agent actually uses the Skill tool on first test run

You only know this by running a task and reading the turn trace. This is the
confirmation that skills are *loaded by the agent*, not just present on disk.

**Run** any quick task (use `chinook001` for speed):
```bash
python -m benchmark.run_dbt_local chinook001 --model claude-sonnet-4-6 2>&1 | tee benchmark/scratch/_preflight_chinook.log
```

**Working**: somewhere in the first ~10 turns, you should see a line like:
```
[HH:MM:SS] [INFO]   TOOL: Skill -> {"skill": "dbt-workflow"}
```
OR
```
[HH:MM:SS] [INFO]   TOOL: Skill -> {"skill": "dbt-debugging"}
```
(the exact skill varies by task). The key is that `Skill` tool calls appear at
all. This proves:
1. The skills were discoverable by Claude Code
2. The `allowed_tools` whitelist isn't shadowing the Skill tool (if it were,
   you'd see zero Skill calls)
3. The prompt and skills are wired correctly

**Broken**: no `TOOL: Skill -> ...` lines anywhere in the run. Probably means
an `allowed_tools` whitelist was re-introduced in `run_dbt_local.py` and
accidentally left out the `Skill` tool. Or the SKILL.md frontmatter is
malformed.

**Fix**: confirm `ALLOWED_TOOLS` is NOT set anywhere in `run_dbt_local.py`
(there should only be a comment explaining why). Grep for it:
```bash
grep -n "ALLOWED_TOOLS\|allowed_tools" benchmark/run_dbt_local.py
```
Should return ONLY the comment lines, never an actual list.

---

### ✅ Check 9 — Agent actually calls `dbt_project_map` early

Even more important than Check 8, because this confirms the main workflow
is hitting the intended tools.

**Look in the same run log from Check 8** for:
```
[HH:MM:SS] [INFO] --- Turn N (Xs) ---
[HH:MM:SS] [INFO]   TOOL: ToolSearch -> {"query": "select:mcp__signalpilot__dbt_project_map,mcp__signalpilot__dbt_project_validate", "max_results": 2}
...
[HH:MM:SS] [INFO] --- Turn N+2 (Xs) ---
[HH:MM:SS] [INFO]   TOOL: mcp__signalpilot__dbt_project_map -> {"project_dir": "C:\\...\\chinook001"}
```

**Working**:
1. `ToolSearch` is called with `select:mcp__signalpilot__dbt_project_map,...`
   (and maybe `dbt_project_validate`) within the first few turns
2. `mcp__signalpilot__dbt_project_map` is actually invoked within the first
   ~6 turns
3. `mcp__signalpilot__dbt_project_validate` is invoked within the first ~8 turns

**Broken — mode A**: `ToolSearch` is called repeatedly (3+ times) with
different queries like `"signalpilot dbt"`, `"mcp signalpilot"`, etc., and
each one returns empty or irrelevant results. This is the failure mode from
Check 4 surfacing inside a real run — the MCP tools aren't in the agent's
toolset. STOP and re-run Check 4.

**Broken — mode B**: `ToolSearch` isn't called at all, and instead the agent
goes straight into `Glob`/`Read`/`Bash` exploration. Means the prompt didn't
mention `dbt_project_map` prominently enough, or the agent isn't reading it.
Check the rendered `_system_prompt.md` for the DBT Project Discovery section.

**Broken — mode C**: `dbt_project_map` is called but returns an error (see
Check 10).

---

### ✅ Check 10 — First `dbt_project_map` call returns real content

When the agent calls `mcp__signalpilot__dbt_project_map` for the first time
in the run, the subsequent message should have a `ToolResultBlock` with
real content. The runner's logging bug (ToolResultBlock was checked inside
AssistantMessage instead of UserMessage) means you WON'T see a `RESULT:`
line in the default logs, but you CAN confirm the call succeeded by checking
that the next AssistantMessage acts on the data.

**Working signal**: within 1-2 turns after the `dbt_project_map` call, you
should see the agent either:
- Calling another tool with specific model names from the project (like
  `focus="model:dim_customer"`), indicating it parsed the project map
- Writing a file with a name that matches a missing model from the project
- Saying something about the project state in AGENT text like "Now let me
  fetch the full contract for each missing model"

**Broken**: the very next turn re-calls `ToolSearch` or tries to call
`dbt_project_map` again with different args. Means the first call returned
an error the agent didn't understand.

**Fix**: capture the actual tool result by running the MCP diagnostic
manually:
```bash
python -c "
import sys; sys.path.insert(0, 'signalpilot/gateway')
from gateway.dbt import build_project_map
print(build_project_map(r'benchmark/test-env/chinook001', focus='work_order'))
"
```
If THIS works but the agent's call doesn't, the issue is in how the MCP
tool forwards arguments or serializes results.

---

### ✅ Check 11 — Default run config hasn't been regressed

Grep for known-bad values:
```bash
grep -n "max_turns=" benchmark/run_dbt_local.py
grep -n "max_budget_usd\|--budget" benchmark/run_dbt_local.py
grep -n "allowed_tools\b" benchmark/run_dbt_local.py
```

**Working**: all three should return ONLY comment lines or the defaults we
expect (`default=200` for max_turns, and no `max_budget_usd=` or
`allowed_tools=` assignments).

**Broken**: someone reintroduced a turn cap below 100, a budget cap, or a
tool whitelist. See anti-patterns #4, #5, #11 in section 7 of this doc.

**Fix**: revert the regression. These are well-known footguns and there's
no good reason to reintroduce them.

---

### ✅ Check 12 — docs are in sync

Quick sanity that we didn't break the doc layout:
```bash
ls benchmark/docs/
```
Should contain at least:
```
continuation-prompt.md
non-determinism-investigation.md
progress.md
runs.md
tools_recommendations.md
```

And grep for the score line:
```bash
grep "^## Score" benchmark/docs/runs.md
```

Should return a `## Score: N/65 evaluable = XX.X%` line. If that line is
missing, docs got mangled — check git log.

---

### Pre-flight completion marker

If all 12 checks pass, write down the current score and timestamp in a
scratch note before making any changes. Example:
```
[2026-04-10 14:32] Pre-flight clean. Baseline: 29/65 = 44.6% per runs.md.
  Starting Category A (date spine) iteration.
```

This gives you a "before" anchor for the iteration you're about to do. If
things go sideways, you can diff against this state.

**Do not start any real work until all 12 checks pass.**

---

## 1. Where things stand (read this before touching code)

### 1.1 Current score and leaderboard
- **29/65 evaluable tasks = 44.6%** (live number in `docs/progress.md`)
- Databao (current #1 public): 30/68 = 44.11%
- 3 tasks are non-evaluable (no gold DB): airbnb002, google_ads001, movie_recomm001
- 36 tasks are failing for documented reasons in `docs/runs.md`

### 1.2 Failure category distribution (from `docs/progress.md`)
| Category | Count | Leverage |
|---|---|---|
| A — Date spine / CURRENT_DATE | 7 | **HIGHEST ROI** — one well-designed fix could flip 3-5 tasks |
| B — Wrong JOIN type (INNER where LEFT) | 4 | Medium — skills exist but agent doesn't consistently apply |
| C — Row count / aggregation errors | 7 | Mixed |
| D — Value / computation errors | 9 | Hard — task-specific logic errors |
| E — Missing / broken build | 3 | Mixed |
| F — Schema / column mismatch | 3 | Fixable with discipline |
| G — Non-deterministic (documented) | 2 | See 1.4 |

### 1.3 What got solved recently (don't redo these)
- **New MCP tools**: `dbt_project_map` and `dbt_project_validate` live in
  `signalpilot/gateway/gateway/dbt/`. Built and verified end-to-end. Full test
  suite at `tests/test_dbt_project_map.py` (43 tests passing).
- **Prompt externalized**: moved from an f-string in code to
  `benchmark/prompts/dbt_local_system.md` + `dbt_local_user.md`. Uses
  `string.Template` with `${var}` placeholders so Jinja `{{ ref('x') }}` stays
  unescaped.
- **Project context removal**: `run_dbt_local.py` no longer dumps every project
  file into the system prompt. Down from 32k chars to ~9k. The agent uses
  `dbt_project_map` + Read/Glob instead.
- **Turn and budget caps lifted**: `max_turns` default raised to 200, `--budget`
  and `max_budget_usd` removed. Validation loops are legitimate work. See
  `run_dbt_local.py` comments.
- **`allowed_tools` whitelist removed**: the agent has access to every Claude
  Code tool plus every `mcp__signalpilot__*` tool plus the `Skill` tool by
  default. Never add an allowlist back — it strands tools the prompt references
  and shadows the Skill tool.
- **MCP PYTHONPATH fix**: the Claude Code CLI strips `cwd` from MCP stdio
  server configs. We now inject `PYTHONPATH` + merged `os.environ` in
  `run_dbt_local.py` so the gateway subprocess can start on Windows.
  Identical pattern also applies in `_verify_mcp_sdk.py`.
- **Gateway store.py Windows shim**: `signalpilot/gateway/gateway/store.py`
  uses a no-op `fcntl` shim on Windows so the MCP server imports cleanly.
- **chinook001 eval config patch**: `fct_invoice` → `fact_invoice` in
  `condition_tabs`. Backup kept at `spider2_eval.jsonl.bak`.
- **Non-determinism investigation**: full deep-dive at
  `docs/non-determinism-investigation.md`. 15-version DuckDB sweep, OHDSI
  upstream check, corpus scan, cascading-trace through synthea001.
  **Read this before touching any ND-related task.**

### 1.4 Known failure classes that are not normal bugs
- **(ND) — Non-determinism in pre-shipped SQL scaffolds**: 7 tasks marked with
  `(**ND**)` in `runs.md`. Root cause: `ROW_NUMBER() OVER (ORDER BY <non-unique>)`
  in upstream files that were shipped unchanged. Inherited from OHDSI/ETL-Synthea.
  **The fix is to empower the agent to proactively rewrite these upstream files**,
  not to patch scaffolding yourself. See section 3.3 below.
- **chinook001 gold-DB infra issue**: gold DB was missing a dbt-generated table
  (`dim_date` vs the committed SQL). Eval config typo fixed; now passing in
  recent runs.

---

## 2. Priority order for your next improvements

Work **top-down** unless you have a strong reason to skip. Higher items are
higher leverage per engineering hour.

### 2.1 Category A — Date spine / CURRENT_DATE (7 tasks)
**This is the highest-ROI work.** Per `progress.md`, affected tasks:
salesforce001, shopify001, xero001, xero_new001, xero_new002, quickbooks003,
pendo001.

**Known root cause**: dbt package models use `current_date` as spine endpoints.
When run in 2026 against gold DBs built in 2024/2025, spines extend past the
gold data's date range and inflate row counts.

**Past attempts that didn't work**:
- Prompt rule "never use current_date for spine endpoints" — agent reads it but
  doesn't override package models
- MCP tool `get_date_boundaries` — returns the right max date, agent
  acknowledges it, but still doesn't edit the package spine model
- Mandatory workflow step 2b — same thing, no action taken

**The gap**: the agent treats files under `dbt_packages/` as read-only. It
needs to learn the **"override" pattern** — if a package model uses `current_date`,
create a local file under `models/` with the same basename, and dbt will prefer
the local version over the packaged one. This is standard dbt practice but the
agent isn't applying it.

**What to build**:
1. A new skill: `dbt-date-spines/SKILL.md`. Cover:
   - How to detect `current_date` / `now()` / `current_timestamp` in package models
   - The local-override pattern (filename-shadowing)
   - How to determine the correct max date for the spine (use
     `get_date_boundaries` MCP tool)
   - The `dbt.current_timestamp_backcompat()` macro specifically
2. A `dbt_project_map` enhancement: detect `current_date` references in
   `dbt_packages/**/*.sql` and surface them in the project map as actionable
   warnings (`⚠ date-spine leak in dbt_utils.date_spine`)
3. A short prompt addition (1-3 lines) pointing to the skill

**Validation plan**: test against `shopify001` (documented improvement path
2654 → 2082 vs gold 2077), `xero001` (1574 → 1194 → 1174 vs 1170), and
`pendo001` (which has both a page_daily_metrics PASS and a guide_daily_metrics
FAIL — tests regression).

If 1-2 of the three flip, extend to a wider sweep.

### 2.2 Category B — Wrong JOIN type (4 tasks)
Tasks: apple_store001, flicks001, playbook002, provider001.

The existing `dbt-workflow` skill covers LEFT JOIN defaults, but the agent isn't
consistently applying it. The root issue is probably that the prompt's workflow
doesn't trigger the skill often enough, or the skill advice is buried.

**What to try**:
- Add a specific rule to `dbt-workflow` skill: "For any model where the task
  description says 'for each X' without an exclusion phrase, the JOIN must be
  LEFT. Use `mcp__signalpilot__compare_join_types` to verify."
- Make the agent call `compare_join_types` explicitly during Step 4 (run and
  fix) for models involving multi-source joins
- Don't modify the main prompt — route this through the skill

### 2.3 Non-determinism empowerment (7 tasks, see docs/non-determinism-investigation.md)
**Read `non-determinism-investigation.md` first.** Do not re-run version sweeps
or try to regenerate the gold. The fix path is:
1. Add a non-determinism scanner to `dbt_project_map`. It should flag any
   `ROW_NUMBER() / RANK() / NTILE() OVER (ORDER BY <single column>)` pattern
   where the column name suggests non-uniqueness.
2. Add or update a skill: `dbt-determinism/SKILL.md`. Cover:
   - How to recognize non-deterministic ORDER BY
   - How to add a stable tiebreaker
   - Why this matters for reproducible SQL
3. Add a short rule to the main prompt: "If `dbt_project_map` flags a
   non-determinism warning in a model upstream of your eval-critical output,
   you are allowed (and encouraged) to rewrite that upstream file to add a
   deterministic tiebreaker."

This treats non-determinism as a normal dbt quality issue (which it is!), not
a benchmark hack. A real production dbt agent would also want this.

### 2.4 Category D — Value / computation errors (9 tasks)
These are the hardest. Each task has task-specific logic errors that the agent's
reasoning isn't catching. Potential angles:
- Better per-model verification — use `mcp__signalpilot__validate_model_output`
  more aggressively
- A "domain understanding" step that re-reads the task description after each
  model build to check for unmet semantic requirements
- Comparing the agent's output against a freshly-described "what should this
  answer look like" sanity check

These are low-priority until A and B are done.

---

## 3. How to run and iterate

### 3.1 Running a single task
```bash
cd $PROJECT_ROOT  # e.g. /path/to/SignalPilot
python -m benchmark.run_dbt_local <task_id> --model claude-sonnet-4-6
```

Defaults: `max_turns=200`, no budget cap, MCP enabled, work dir at
`benchmark/test-env/<task_id>/`. Skills copied automatically.

For opus on harder tasks:
```bash
python -m benchmark.run_dbt_local <task_id> --model claude-opus-4-6
```

### 3.2 Running a small batch (1-3 tasks)
Run each task individually and compare scores. Do not use `run_batch.py` for
iteration — that's for sweeps. For iteration:
```bash
python -m benchmark.run_dbt_local shopify001
python -m benchmark.run_dbt_local xero001
python -m benchmark.run_dbt_local pendo001
```

Record results in a scratch file under `benchmark/scratch/` — never commit them.

### 3.3 Inspecting a run
After a run, the important artifacts are:
- `benchmark/test-env/<task>/` — the work dir (will be wiped on next run)
- `benchmark/test-env/<task>/_system_prompt.md` — exact prompt passed to agent
- `benchmark/test-env/<task>/models/**/*.sql` — what the agent wrote
- `benchmark/test-env/<task>/<db>.duckdb` — the built database
- `benchmark/test-env/<task>/agent_result.json` — agent transcript summary (if written)
- `benchmark/scratch/<name>_run.log` — full stdout if you piped it via `tee`

When a task flips PASS → FAIL or vice versa, always check the turn trace to
confirm the mechanism, not just the outcome.

### 3.4 Verifying an MCP change didn't break the server
Always re-run `benchmark/_verify_mcp_sdk.py` after editing anything in
`signalpilot/gateway/gateway/`. That's the canonical "does the MCP still work
through the SDK" smoke test.

```bash
python benchmark/_verify_mcp_sdk.py
```

Look for `signalpilot: connected` in the init message, not `signalpilot: failed`.

### 3.5 Running the unit tests
```bash
python -m pytest tests/test_dbt_project_map.py
```

43 tests. Should pass in ~1.5 seconds. Run after any change under
`signalpilot/gateway/gateway/dbt/`.

---

## 4. Loop structure per improvement attempt

Do **all** of these steps every time, in order. Shortcuts here are how projects
drift.

### Step 1: Orient
Re-read `docs/progress.md` and the failing-task table in `docs/runs.md`. Confirm
the failure category you're targeting still exists and is still the best use of
time.

### Step 2: Pick a target
Choose 1-3 failing tasks from the target category. One should be the clearest
instance of the failure. One should be a task that was passing (to catch
regressions). Optionally one more from a different category (generalization
check).

### Step 3: Deep-read one failing task
Don't guess at the fix. Read the failing task's:
- Task instruction in the jsonl
- Scaffold SQL files (missing + stub + complete)
- The eval config entry in `spider2_eval.jsonl`
- The gold DB (**read-only, don't leak into the agent**) to understand what
  "correct" looks like numerically
- The agent's last run transcript for that task (if available in scratch)

Form a specific hypothesis. "The agent doesn't know about local package
overrides" is good. "Just make it try harder" is bad.

### Step 4: Brainstorm angles
Before implementing, spend 3-5 minutes thinking about:
- **Is this a prompt, skill, MCP tool, or infrastructure change?** Prefer skill
  > MCP tool > prompt > infra, in that order. Infra changes are the most
  expensive and often benchmark-specific.
- **Would this help in a real production dbt project?** If no, reconsider.
- **What's the smallest possible version of the change?** Start there.
- **What could this break?** Pick the regression-check task with that risk in
  mind.
- **Is there already a tool/skill that should have solved this?** Sometimes
  the fix is "make the existing tool more discoverable" rather than "build a
  new one".
- **Could this be two changes?** If yes, split them and validate one at a time.
- **Would a web search reveal a known pattern?** Use WebSearch. Specifically
  look at recent (last 12 months) dbt agent posts, Anthropic / OpenAI blog
  entries on coding agents, and the dbt package index for relevant utilities.

### Step 5: Implement minimally
- Update / create a skill file if it's domain knowledge
- Add an MCP tool method only if the agent needs a capability it can't get via
  existing tools
- Edit the main prompt only if the structural workflow itself needs to change
- Update `run_dbt_local.py` only for runner-level concerns (never for task logic)

Keep diffs small. Each change should be one logical improvement.

### Step 6: Run the 1-3 test tasks
Run each task individually. Record the result in your scratch notes. Note the
turn count, cost (if visible), and whether it passed.

### Step 7: Verify the mechanism
For each task that changed state:
- If PASS → FAIL on a previously-passing task: rollback immediately
- If FAIL → PASS on the target task: read the turn trace. Confirm the agent
  used the expected tool / skill / workflow step. If it passed for a different
  reason, treat it as "lucky" and don't count it
- If FAIL → FAIL: iterate on the hypothesis, not on the implementation. Rebuild
  your mental model of why the task fails

### Step 8: Update docs
- Add a one-line entry to `docs/progress.md` describing the change and its
  impact
- Update the relevant row(s) in `docs/runs.md`
- If you discovered a new failure class, create a new doc under `docs/` similar
  to `non-determinism-investigation.md`

### Step 9: Decide whether to sweep
Only if all of:
- Your change is stable on 1-3 tasks
- You have a prior score baseline for comparison
- You haven't done a full sweep in the last ~few iterations
- The change is large enough that a sweep tells you something you don't already know

---

## 5. Brainstorming angles between runs

When you're stuck or just thinking about the next move, cycle through these
lenses.

### 5.1 Tool lens
- Which `mcp__signalpilot__*` tool did the agent underuse?
- Is there a pattern the agent does manually that should be a tool?
- Is there a tool the agent misuses (e.g., calls it with wrong arguments)?
- Could a new tool consolidate 3+ agent turns into 1?
- Is there a tool description that's misleading?

### 5.2 Skill lens
- What pattern keeps recurring in failure modes?
- Which skill is the most invoked, and does it cover the actual common cases?
- Which skill is never invoked, and should it be merged or removed?
- Is there a dbt pattern community-known (e.g., from dbt-labs docs) that we
  don't capture?

### 5.3 Prompt lens
- Where is the agent making wrong assumptions (visible in turn traces)?
- Which workflow step is the agent skipping or short-circuiting?
- Is there a section of the prompt the agent consistently ignores?
- Has the prompt grown and could it shrink?

### 5.4 Research lens
- What's new in dbt in the last 6 months?
- What's new in the Claude Code CLI, Agent SDK, or MCP spec?
- Are there new MCP servers (for dbt, duckdb, git, etc.) that solve problems
  we've been solving by hand?
- What are other agent teams publishing about?
- Any relevant academic papers on code agents, SQL agents, or text-to-SQL?

### 5.5 Production lens
- Imagine you ship this agent to a dbt consulting firm tomorrow. What's the
  first thing a real engineer would complain about?
- Which of our "wins" would look weird in a code review?
- Is any of our behavior Spider2-specific in a way that would embarrass us?

### 5.6 Failure-mode lens
- For tasks with the same failure pattern, is there a common upstream structure?
- Does the failure happen at compile time, run time, or eval time?
- Is the failure from missing information (fix with a tool/skill) or from bad
  reasoning (fix with better prompting)?
- Would a different model (opus vs sonnet) handle it better? If so, is that
  prompt/skill work or is the task genuinely harder?

---

## 6. Files you should know

### Code
- `benchmark/run_dbt_local.py` — local runner (no Docker). Main entry point.
- `benchmark/run_direct.py` — thin shim → `benchmark/runners/direct.py` (older runner)
- `benchmark/run_batch.py` — batch runner for full sweeps (don't use for iteration)
- `benchmark/run_dbt_single.py` — Docker runner
- `benchmark/agent/sdk_runner.py` — Claude Agent SDK wrapper (shared helpers)
- `benchmark/agent/prompts.py` — `run_direct.py`'s prompt builder
- `benchmark/core/mcp.py` — MCP server loader (shared)
- `benchmark/core/paths.py` — canonical paths
- `benchmark/dbt_tools/` — static analysis helpers for scaffolding
- `signalpilot/gateway/gateway/dbt/` — `dbt_project_map` + `dbt_project_validate` MCP module
- `signalpilot/gateway/gateway/mcp_server.py` — MCP tool registrations (bloated, 2500+ lines)
- `signalpilot/gateway/gateway/store.py` — connection store (Windows fcntl shim in place)
- `tests/test_dbt_project_map.py` — MCP tool tests (43)

### Prompts and skills
- `benchmark/prompts/dbt_local_system.md` — main system prompt for `run_dbt_local`
- `benchmark/prompts/dbt_local_user.md` — user prompt template
- `benchmark/skills/dbt-workflow/SKILL.md` — core dbt workflow
- `benchmark/skills/dbt-verification/SKILL.md` — post-build checks
- `benchmark/skills/dbt-debugging/SKILL.md` — error recovery
- `benchmark/skills/duckdb-sql/SKILL.md` — DuckDB patterns

### Docs
- `benchmark/docs/progress.md` — overall project status (update this!)
- `benchmark/docs/runs.md` — per-task status table (update this!)
- `benchmark/docs/non-determinism-investigation.md` — full ND investigation
- `benchmark/docs/tools_recommendations.md` — MCP tool ideas
- `benchmark/docs/continuation-prompt.md` — **this file**

### Reference material (read-only, clone, no edits)
- `benchmark/ref/spider/` — full Spider2 repo clone
- `benchmark/ref/synthea-omop-etl/` — OHDSI/ETL-Synthea upstream for synthea001
- `benchmark/ref/Dockerfile.spider-eval` — reproducible pinned-version image (built as `sp-spider2-eval`)

### Ignored / scratch (safe to put experiments here)
- `benchmark/scratch/` — throwaway experiments, logs, DB copies
- `benchmark/test-env/` — per-run work dirs (wiped each run)

---

## 7. Anti-patterns — don't do these

1. **Modifying or regenerating the gold.** See section 0.9.
2. **Hardcoding task names** in prompts, skills, or tools.
3. **Providing column names from specific tasks** in the prompt.
4. **Adding an `allowed_tools` whitelist** to any runner. It strands tools.
5. **Raising the main prompt back above ~8k chars** by inlining examples.
6. **Dumping project context into the system prompt.** Use tools + Read.
7. **Running a 65-task sweep during iteration.** Hours and dollars wasted.
8. **Calling a fix "done" based on score alone** without reading the turn trace.
9. **Committing changes that you haven't actually run** against a test task.
10. **Making the agent's life easier by editing test-env files** mid-run.
11. **Lowering `max_turns` or reintroducing a budget cap** because a task "took too long".
12. **Chasing DuckDB versions** for non-determinism. See
    `non-determinism-investigation.md` — it was already tried, definitively
    doesn't work.
13. **Writing a new MCP tool that duplicates an existing one** — check
    `mcp_server.py` first.
14. **Changing the prompt and not running any tasks** to verify the change.
15. **Leaking the fact that the agent is being benchmarked** into its context.
    The agent should behave identically whether it's on Spider2 or a real
    customer project.

---

## 8. Your first ~hour of work

If you're a fresh session, do exactly this, in order:

1. Read `docs/progress.md` end-to-end (5 min)
2. Read `docs/runs.md` end-to-end (10 min)
3. Read `docs/non-determinism-investigation.md` skim, then the recommendations
   section in detail (10 min)
4. Re-read section 0 of this file to make sure the principles are loaded (5 min)
5. **Run the entire pre-flight checklist (section 0.11 of this doc).** Do not
   skip any of the 12 checks. This is where silent infrastructure failures
   get caught. Plan ~10 min for this the first time you do it. (10 min)
6. Write down your pre-flight completion marker with the current baseline
   score. (1 min)
7. Pick Category A (date spine) as your first target
8. Run `python -m benchmark.run_dbt_local shopify001` with the current agent,
   **just to see the baseline behavior** — do not change anything yet (5-10 min)
9. Read the turn trace carefully. Confirm via Checks 8, 9, 10 of the pre-flight
   that the MCP tools and skills are actually being exercised on this real run
   before you draw any conclusions. If they aren't, re-run Check 4 before
   going further.
10. Identify the specific point where the agent fails to override the package
    date spine (5 min)
11. Write down your hypothesis (1 sentence) and the smallest possible change
    that tests it
12. Begin the loop in section 4

This is a disciplined, research-driven project. Fast iteration with small
changes beats heroic rewrites. The benchmark will reward patience more than
cleverness.

Good luck. Keep the main prompt slim. Don't leak the gold. Build the best dbt
agent, not the best Spider2 submitter.
