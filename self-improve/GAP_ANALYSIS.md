# gstack → SignalPilot Gap Analysis

## Phase 1: Gap Analysis

### Product/CEO Review

**Current state:** SignalPilot's CEO continuation (`ceo-continuation.md`) acts as a task assigner between rounds — it reviews elapsed time, commits, and cost, then assigns the next task. It does NOT challenge product assumptions, rethink the problem space, or evaluate whether the agent is building the right thing.

**What gstack provides (gstack-plan-ceo-review):**
- **Founder-mode thinking**: Challenges premises, asks "are we solving the right problem?"
- **Scope modes**: Four distinct modes — SCOPE EXPANSION (find the 10-star product), SELECTIVE EXPANSION (expand only where it creates outsized value), HOLD SCOPE (stay the course), SCOPE REDUCTION (cut scope to ship faster)
- **Product vision**: Evaluates whether the implementation serves the user, not just whether it's technically correct
- **Challenge assumptions**: Actively looks for blind spots in the plan

**Gap severity: HIGH** — Without product-level review, the self-improvement agent optimizes for technical correctness but may miss higher-value improvements or solve the wrong problems entirely.

### Design Review

**Current state:** SignalPilot has a `frontend-builder` agent for building UI and a `reviewer` that checks code quality, but NO agent evaluates design quality — visual consistency, spacing, hierarchy, accessibility, or whether the UI "feels right."

**What gstack provides:**
- **gstack-design-review**: Post-implementation visual QA — finds spacing issues, hierarchy problems, inconsistent patterns, "AI slop" (generic/template-looking UI), slow interactions
- **gstack-plan-design-review**: Pre-implementation design review — rates each design dimension 0-10, explains what a 10 would look like, then rewrites the plan to hit higher scores
- **Design dimensions scored**: Layout, typography, color, spacing, hierarchy, interaction, accessibility, consistency, delight

**Gap severity: MEDIUM** — SignalPilot is primarily a backend text-to-SQL system, but it has a monitoring dashboard and web UI that benefit from design review. More importantly, as the frontend grows, having no design QA means visual debt accumulates silently.

### Engineering Review (Pre-Implementation)

**Current state:** SignalPilot's `reviewer` runs AFTER implementation — it catches bugs, security issues, and code quality problems post-hoc. There is NO pre-implementation architecture review.

**What gstack provides (gstack-plan-eng-review):**
- **Architecture critique**: Before writing code, evaluate whether the approach is sound
- **Scalability review**: Will this design handle 10x traffic? 100x data?
- **Maintainability analysis**: Is this going to be easy or painful to change later?
- **Alternative approaches**: Are there simpler or more robust ways to solve this?
- **Risk identification**: What could go wrong? What are the failure modes?

**Gap severity: HIGH** — The current loop is: plan → implement → review → fix. Adding pre-implementation review changes it to: plan → review plan → implement → review code. This catches architectural mistakes BEFORE they're built, saving entire rounds of rework.

### QA & Testing

**Current state:** SignalPilot's `test-writer` writes tests and runs them. It does NOT perform full QA — it doesn't systematically explore edge cases, test integration points, verify error handling paths, or create regression tests for bugs found during review.

**What gstack provides (gstack-qa):**
- **Full QA workflow**: Not just "write tests" but "systematically verify the system works"
- **Bug finding + fixing cycle**: Find a bug → write a test for it → fix it → verify the fix
- **Integration testing**: Test how components work together, not just in isolation
- **Regression prevention**: After fixing bugs, ensure they stay fixed
- **Edge case exploration**: Systematically probe boundaries and unusual inputs

**Gap severity: MEDIUM** — The test-writer creates tests, but a QA agent would close the loop: find bugs, prove them with tests, fix them, verify. This is especially valuable for SignalPilot's SQL engine and database connectors where edge cases are common.

### Other Critical Gaps

**Investigation/Debugging (gstack-investigate):**
- SignalPilot has no dedicated debugging agent. When the worker encounters a failing test or broken feature, it tries to fix it inline, often treating symptoms rather than root causes.
- A dedicated investigator would: reproduce the issue → trace the root cause → understand why → fix the cause, not the symptom.
- **Gap severity: MEDIUM-HIGH** — Root cause analysis prevents the same bugs from recurring in different forms.

**Security Guard (gstack-guard):**
- SignalPilot's reviewer includes security checks, but they're one section among many. A dedicated security agent would go deeper: analyze auth flows end-to-end, check for OWASP Top 10, verify input validation at every boundary, audit dependency versions.
- **Gap severity: MEDIUM** — SignalPilot handles database credentials and SQL queries, making security review particularly important.

**Code Health (gstack-health):**
- No scored health metrics. The reviewer flags issues qualitatively, but doesn't produce quantitative scores that track improvement over time.
- **Gap severity: LOW** — Nice to have for tracking improvement trends, but not critical for autonomous operation.

**Retrospective (gstack-retro):**
- No learning mechanism between runs. Each session starts fresh without institutional knowledge of what worked and what didn't.
- **Gap severity: LOW-MEDIUM** — The memory system partially addresses this, but a structured retro could identify systematic patterns.

---

## Phase 2: Architecture Recommendations

### Agent Architecture Patterns

All new agents follow SignalPilot's existing pattern:
1. **AgentDefinition** in `main.py` subagents dict
2. **Prompt file** at `prompts/agent-{name}.md`
3. **Tool restrictions** based on agent purpose
4. **Model selection** based on analysis depth needed

### Tool Selection Guidelines

| Agent Type | Tools | Rationale |
|---|---|---|
| Read-only analysis/review | `["Read", "Glob", "Grep", "Bash"]` | Cannot modify code, only analyze |
| Code modification/fixing | `["Read", "Write", "Edit", "Bash", "Glob", "Grep"]` | Full write access for implementation |
| Research/investigation | `["Read", "Glob", "Grep", "Bash", "WebSearch", "WebFetch"]` | Read + web for external context |

### Model Selection Strategy

| Use Case | Model | Rationale |
|---|---|---|
| Deep analysis, critique, review | `opus` | Thorough reasoning, catches subtle issues |
| Code generation, test writing | `sonnet` | Fast execution, good enough for implementation |
| Plan review, architecture | `opus` | Needs to reason about tradeoffs |
| Bug investigation | `sonnet` | Execution-heavy, needs to run code |
| Security audit | `opus` | Must be thorough, security is critical |

---

## Phase 3: Priority Ranking

### Tier 1 (Must Have)
1. **plan-reviewer**: Pre-implementation plan and architecture review — catches design mistakes before they become code. Combines the best of gstack-plan-ceo-review and gstack-plan-eng-review.
2. **design-reviewer**: Visual QA and design consistency review for frontend changes — prevents UI quality degradation.
3. **qa**: Full QA workflow that goes beyond test writing — find bugs, prove them, fix them, verify.
4. **investigator**: Root-cause debugging agent — stops symptom-fixing and ensures real problems get solved.
5. **security-guard**: Deep security-focused review — essential for a system handling database credentials and SQL.

### Tier 2 (Should Have)
1. **health-checker**: Quantitative code health scoring — track improvement across runs
2. **retro**: Post-session retrospective — capture what worked for future sessions

### Tier 3 (Nice to Have)
1. **careful**: Extra-cautious mode for critical file changes
2. **benchmark-runner**: Dedicated agent for running and analyzing Spider2 benchmarks
3. **release-notes**: Auto-generate release documentation from commits

---

## Phase 4: Implementation Specifications

See the individual agent prompt files in `prompts/agent-{name}.md` and their definitions in `agent/main.py`.

### Summary of New Agents

| Agent | Model | Tools | Purpose |
|---|---|---|---|
| `plan-reviewer` | opus | Read, Glob, Grep, Bash | Pre-implementation plan/architecture review |
| `design-reviewer` | opus | Read, Glob, Grep, Bash | Visual QA and design consistency |
| `qa` | sonnet | Read, Write, Edit, Bash, Glob, Grep | Full QA workflow: find → test → fix → verify |
| `investigator` | sonnet | Read, Write, Edit, Bash, Glob, Grep | Root-cause debugging and systematic investigation |
| `security-guard` | opus | Read, Glob, Grep, Bash | Deep security audit focused on OWASP Top 10 |
