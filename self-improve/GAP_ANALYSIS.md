# gstack → SignalPilot Gap Analysis

Analysis of the gstack agent ecosystem to identify missing capabilities in SignalPilot's self-improvement agent. All Tier 1 gaps have been implemented.

---

## Phase 1: Gap Analysis

### Product/CEO Review
**Gap:** SignalPilot's CEO continuation prompt was a generic task router — it assigned the next task based on time/commits/cost but never challenged assumptions, evaluated architecture, or assessed scope.

**What gstack provides:** Founder-mode thinking with 4 scope modes (EXPANSION, SELECTIVE EXPANSION, HOLD, REDUCTION), product vision evaluation, premise challenging.

**Status: IMPLEMENTED** — `plan-reviewer` agent (`prompts/agent-plan-reviewer.md`) for pre-implementation review, plus the CEO continuation prompt (`prompts/ceo-continuation.md`) was rewritten to incorporate scope assessment, premise challenging, and architecture evaluation directly into the CEO loop.

### Design Review
**Gap:** No agent evaluated design quality — visual consistency, spacing, hierarchy, accessibility, or "AI slop" detection. The `frontend-builder` builds UI but nothing reviews it.

**What gstack provides:** Post-implementation visual QA with dimension scoring (0-10), pre-implementation design review, AI slop pattern detection.

**Status: IMPLEMENTED** — `design-reviewer` agent (`prompts/agent-design-reviewer.md`). Scores 6 dimensions 0-10: visual consistency, hierarchy & layout, typography, interaction design, accessibility, overall polish.

### Engineering Review (Pre-Implementation)
**Gap:** SignalPilot's `reviewer` only runs AFTER implementation. No pre-implementation architecture review existed. The loop was: plan → implement → review → fix. Architectural mistakes were caught too late.

**What gstack provides:** Pre-implementation architecture critique — scalability, maintainability, simplicity, alternative approaches, risk identification.

**Status: IMPLEMENTED** — Combined into `plan-reviewer` which evaluates both product value AND architecture soundness. Returns architecture ratings (1-5) for scalability, maintainability, simplicity, and robustness.

### QA & Testing
**Gap:** `test-writer` generates tests but doesn't perform full QA — no systematic edge case exploration, no bug-finding-then-fixing cycle, no integration testing strategy.

**What gstack provides:** Full QA workflow: find bugs → write tests proving them → fix → verify. Systematic edge case probing, regression prevention.

**Status: IMPLEMENTED** — `qa` agent (`prompts/agent-qa.md`). Runs a 6-step QA cycle: understand changes → identify risk areas → write targeted tests → run and find bugs → fix bugs → regression check.

### Investigation/Debugging
**Gap:** No dedicated debugging agent. When the worker hits a failing test, it guesses at fixes, often treating symptoms instead of root causes.

**What gstack provides:** Systematic debugging — reproduce first, gather evidence, form hypotheses, test them, fix the root cause, check for similar patterns elsewhere.

**Status: IMPLEMENTED** — `investigator` agent (`prompts/agent-investigator.md`). Uses a 6-step investigation process with anti-patterns to avoid (shotgun debugging, symptom fixing, premature fixing).

### Security
**Gap:** The `reviewer` includes security checks as one section among many. No deep, dedicated security audit for a system that handles database credentials and executes SQL.

**What gstack provides:** Dedicated security-focused review covering OWASP Top 10, auth flows, credential handling, injection attacks, dependency security.

**Status: IMPLEMENTED** — `security-guard` agent (`prompts/agent-security-guard.md`). Covers injection attacks, auth/authz, data exposure, input validation, and SignalPilot-specific concerns (credential storage, SQL generation safety, sandbox escape, API gateway).

### Remaining Gaps (Not Implemented)
- **Code health scoring** (gstack-health) — quantitative metrics tracking improvement over time. Severity: LOW.
- **Retrospective** (gstack-retro) — structured learning between runs. Severity: LOW-MEDIUM.
- **Deployment automation** (gstack-ship, gstack-land-and-deploy) — not needed for self-improvement agent context.
- **Browser automation** (gstack-browse) — partially addressed by existing `frontend-debug` skill with Playwright MCP.

---

## Phase 2: Architecture

### Module Structure
Agent definitions were extracted from `main.py` into `agent/subagents.py` — a dedicated module with `build_subagent_definitions()` that returns all 10 agents. This was part of splitting the main.py god file (1197 lines) into focused modules:

| Module | Lines | Responsibility |
|---|---|---|
| `main.py` | 55 | FastAPI app, lifespan, entry point |
| `signals.py` | 136 | Signal queue, shared run state, pulse checker |
| `runner.py` | 771 | run_agent, resume_agent, shared `_run_loop()` |
| `endpoints.py` | 237 | All HTTP route handlers via APIRouter |
| `subagents.py` | 79 | All 10 agent definitions |

### Tool Selection Guidelines

| Agent Purpose | Tools | Model |
|---|---|---|
| Read-only review/analysis | `Read, Glob, Grep, Bash` | opus |
| Code modification/fixing | `Read, Write, Edit, Bash, Glob, Grep` | sonnet |
| Research (read + web) | `Read, Glob, Grep, Bash, WebSearch, WebFetch` | sonnet |

### Review Workflow (from `system.md`)
1. **Before complex changes** → `plan-reviewer` (validates approach)
2. **After every feature** → `reviewer` (mandatory, catches implementation issues)
3. **After frontend changes** → `design-reviewer` (alongside reviewer)
4. **For security-sensitive changes** → `security-guard` (alongside reviewer)
5. **When debugging is hard** → `investigator` (root-cause analysis)
6. **For thorough QA** → `qa` (full find-fix-verify cycle)

---

## Phase 3: Priority Ranking

### Tier 1 — Implemented
1. **plan-reviewer** (opus, read-only) — Pre-implementation plan/architecture review with scope modes. ✓
2. **design-reviewer** (opus, read-only) — Visual QA scoring across 6 dimensions. ✓
3. **qa** (sonnet, read-write) — Full QA cycle: find → test → fix → verify. ✓
4. **investigator** (sonnet, read-write) — Root-cause debugging with hypothesis testing. ✓
5. **security-guard** (opus, read-only) — Deep OWASP Top 10 security audit. ✓

### Tier 2 — Not Yet Implemented
1. **health-checker** — Quantitative code health scoring to track improvement trends
2. **retro** — Post-session retrospective to capture what worked

### Tier 3 — Not Yet Implemented
1. **careful** — Extra-cautious mode for critical file changes
2. **benchmark-runner** — Dedicated Spider2 benchmark execution and analysis
3. **release-notes** — Auto-generate release documentation from commits

---

## Phase 4: Implementation Specifications

### plan-reviewer
```python
"plan-reviewer": AgentDefinition(
    description="Use BEFORE implementing a complex feature or architectural change. Reviews the plan for product value, architecture soundness, scalability, and scope. Returns a verdict (SCOPE EXPANSION, SELECTIVE EXPANSION, HOLD SCOPE, or SCOPE REDUCTION) with specific recommendations. Runs on Opus for deep strategic thinking.",
    prompt=prompt.load_agent_prompt("plan-reviewer"),
    model="opus",
    tools=["Read", "Glob", "Grep", "Bash"],
),
```
**Prompt** (`agent-plan-reviewer.md`, 68 lines): Founder + engineer mindset. 5-step review: understand → challenge premise → evaluate architecture (scalability, maintainability, simplicity, robustness rated 1-5) → assess scope (4 modes) → assess risks. Returns verdict, architecture ratings, recommended changes, risks, and revised plan.

**Integration**: Referenced in system.md review workflow, CEO continuation prompt scope assessment, and continuation phases 1 and 4.

### design-reviewer
```python
"design-reviewer": AgentDefinition(
    description="Use after frontend changes to review UI/UX quality. Scores visual consistency, hierarchy, typography, interaction design, and accessibility on a 0-10 scale. Catches spacing issues, AI slop patterns, and design inconsistencies. Runs on Opus for thorough design analysis.",
    prompt=prompt.load_agent_prompt("design-reviewer"),
    model="opus",
    tools=["Read", "Glob", "Grep", "Bash"],
),
```
**Prompt** (`agent-design-reviewer.md`, 73 lines): Designer's eye. Reviews visual consistency, hierarchy, typography, interaction design, accessibility, and AI slop patterns. Returns a score card (6 dimensions, each 0-10), critical/improvement/polish issue lists, and "what would make this a 10" description.

**Integration**: Referenced in system.md review workflow, continuation phases 5 and 6.

### qa
```python
"qa": AgentDefinition(
    description="Use for full QA cycles — systematically finds bugs, proves them with tests, fixes them, and verifies fixes. Goes beyond test-writer by probing edge cases, integration points, and failure conditions. Use when you need thorough quality assurance, not just test generation.",
    prompt=prompt.load_agent_prompt("qa"),
    model="sonnet",
    tools=["Read", "Write", "Edit", "Bash", "Glob", "Grep"],
),
```
**Prompt** (`agent-qa.md`, 60 lines): QA engineer mindset. 6-step workflow: understand changes → identify risk areas → write targeted tests → run and find bugs → fix bugs (root cause, not symptom) → regression check. Returns summary with counts (tests written, bugs found/fixed, regressions caught) and detailed bug reports.

**Integration**: Referenced in system.md review workflow, continuation phases 1, 2, and 3, and default continuation.

### investigator
```python
"investigator": AgentDefinition(
    description="Use when encountering a bug, failing test, or unexpected behavior that isn't immediately obvious. Systematically traces root causes instead of fixing symptoms. Reproduces the issue, forms hypotheses, tests them, and fixes the underlying problem.",
    prompt=prompt.load_agent_prompt("investigator"),
    model="sonnet",
    tools=["Read", "Write", "Edit", "Bash", "Glob", "Grep"],
),
```
**Prompt** (`agent-investigator.md`, 66 lines): Systematic debugger. 6-step process: reproduce → gather evidence → form hypotheses → test hypotheses → fix root cause → verify and document. Includes anti-patterns to avoid (shotgun debugging, symptom fixing, blame shifting, premature fixing). Checks for same bug pattern in other files.

**Integration**: Referenced in system.md review workflow, continuation phases 2 and 3, and default continuation.

### security-guard
```python
"security-guard": AgentDefinition(
    description="Use for deep security audits focused on OWASP Top 10, credential handling, SQL injection, auth flows, and data exposure. More thorough than the reviewer's security section. Essential for changes touching auth, database credentials, SQL generation, or API endpoints. Runs on Opus for exhaustive analysis.",
    prompt=prompt.load_agent_prompt("security-guard"),
    model="opus",
    tools=["Read", "Glob", "Grep", "Bash"],
),
```
**Prompt** (`agent-security-guard.md`, 72 lines): Security engineer mindset. Audits injection attacks (SQL, command, XSS, path traversal), auth/authz, data exposure, input validation, dependency security, and SignalPilot-specific concerns (credential storage, SQL generation safety, sandbox isolation, API gateway). Returns findings by severity (CRITICAL/HIGH/MEDIUM/LOW) with evidence and specific fixes.

**Integration**: Referenced in system.md review workflow, continuation phases 1, 5, and 6.

---

## Changes Made

### Commit 1: `9c7b0cb` — Add 5 new subagents
- Created 5 new agent prompt files (`agent-{plan-reviewer,design-reviewer,qa,investigator,security-guard}.md`)
- Registered all 5 in `subagents.py` (extracted from main.py)
- Updated `system.md` with new agent descriptions
- Created initial `GAP_ANALYSIS.md`

### Commit 2: `8b41421` — Split main.py god file
- Split 1197-line `main.py` into 4 modules: `main.py` (55), `signals.py` (136), `runner.py` (771), `endpoints.py` (237)
- Deduplicated run_agent/resume_agent into shared `_run_loop()`
- Fixed dead code (`or True` condition, unreachable `rate_limited` branch)
- Fixed resume_agent to use full CEO continuation (was degraded)

### Commit 3: `5e50fed` — Upgrade CEO continuation prompt
- Rewrote `ceo-continuation.md` to think like a founder: challenge premises, assess scope (4 modes with time-based guidance), evaluate architecture quality, consider product vision
- Added "Review Workflow" section to `system.md`

### Commit 4: `2f92bb4` — Update continuation phase prompts
- Added agent references to all 7 continuation prompts (phases 1-6 + default)
- Each phase now references the agents that fit its focus

### Commit 5: `4fba02d` — Enrich original agent prompts
- Upgraded all 5 original agent prompts with SignalPilot-specific context
- Added codebase patterns, testing stacks, output formats, and high-risk areas
- All 10 agents now have consistent depth and quality
