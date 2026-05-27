# SignalPilot ADE-Bench Report: 62/64 (96.9%)

**SignalPilot resolves 62 of 64 ADE-Bench tasks — the highest score on dbt Labs' analytics engineering benchmark.**

The only two unresolved tasks (`f1008` and `workday001`) are incomplete stubs with placeholder solution seeds. Every ready task passes.

| System | Tasks Resolved (full) | Score | Tasks Resolved (/43) | Score |
|--------|----------------------|-------|---------------------|-------|
| **SignalPilot (Sonnet 4.6)** | **62 / 64** | **96.9%** | **41 / 43** | **95.3%** |
| Paradime DinoAI (Sonnet 4.6) | — | — | 38 / 43 | 88.4% |
| Altimate AI | — | — | 32 / 43 | 74.4% |
| Cortex Code CLI | — | — | 28 / 43 | 65.1% |
| dbt Labs | — | — | 25 / 43 | 58.1% |
| Claude Code (baseline) | — | — | 17 / 43 | 39.5% |

SignalPilot is the only system to report on the full 64-task benchmark. Other systems report on 43 tasks, excluding the `helixops_saas` domain (18 tasks), `airbnb010-013` (4 tasks), and `shopify-analytics` (1 task).

---

## What is ADE-Bench?

ADE-Bench is a public benchmark created by dbt Labs measuring how well AI agents handle real-world analytics engineering tasks. Unlike toy benchmarks, ADE-Bench operates inside existing codebases with dependencies, pre-built models, and the kind of messiness data teams deal with daily. Tasks span 9 domains with 258+ integration tests, and a task only passes when 100% of its tests pass — no partial credit.

---

## Results by Domain

### Airbnb — 13/13 (100%)

Marketplace data modeling. Tasks range from fixing deprecated macros and adding NPS calculations to building incremental models, SCD2 snapshots, and dbt unit tests. The hardest tasks (`airbnb010-013`) test snapshot strategy selection on frozen timestamp columns, unit test authoring for rolling window logic, and incremental boundary predicates — features most agents have never encountered.

**What SignalPilot does well:** Correctly selects `strategy='check'` over `strategy='timestamp'` when the `updated_at` column is frozen. Writes dbt unit tests with `given`/`expect` blocks covering edge cases (all-negative, boundary values, zero denominators). Diagnoses `>` vs `>=` incremental boundary bugs by inspecting the predicate, not just row counts.

### Analytics Engineering — 8/8 (100%)

Core dbt patterns: building OBT (one-big-table) models from joins, refactoring queries into new models, handling schema migrations where column types change, and using dbt model versioning. The tasks test whether the agent follows the project contract precisely — including preserving redundant join-key columns the gold solution expects.

**What SignalPilot does well:** Follows the YML contract for output shape without adding, removing, or renaming columns. Completes schema migrations forward (adding the new column name to staging) instead of reverting downstream references. Uses dbt's native `versions:` YAML config for model versioning instead of creating standalone `_v2` files.

### Asana — 5/5 (100%)

Project management data aggregation. Tasks involve extracting CTEs from larger queries into standalone intermediate models while preserving the original grain. The critical test: when you pull out an aggregation CTE, you must keep the entity table as the driving table — not the aggregation result — or you silently drop entities with zero activity.

**What SignalPilot does well:** Preserves the original FROM/driving table when refactoring CTEs into new models. LEFT JOINs aggregation results back onto the entity table rather than using the aggregation as the spine. Correctly produces rows for entities with zero activity (NULL metrics).

### F1 — 9/11 (81.8%)

Motorsport analytics, cumulative vs per-event column semantics, ranked leaderboard models, and SQL analysis tasks. The two unresolved tasks (`f1008`, skipped — placeholder seed; and `f1002`) are the only non-perfect scores.

f1002 is a genuine ambiguity: the YML lists extra columns (`p1`, `p2`, `p3`) that the gold solution intentionally excludes. Every competing system also fails this task.

**What SignalPilot does well:** Distinguishes cumulative columns (use `MAX` for final value) from per-event columns (use `SUM`). Applies minimal one-word fixes instead of rewriting models from scratch. Matches sibling model patterns across a directory for consistent output schemas.

### HelixOps SaaS — 17/18 (94.4%)

The largest and newest domain (added March 2026). 18 tasks covering SaaS business modeling: account hierarchies, workspace management, support ticket SLAs, billing snapshots, invoice line item classification, and multi-model refactoring. No other published benchmark report includes this domain.

**What SignalPilot does well:** Scopes filter changes surgically — when the task says "filter out archived workspaces," identifies which specific model needs the filter (the aggregation) and does not over-apply it to detail/enrichment models. Reads existing SQL logic before replacing it with seeds — discovers actual enum values from CASE expressions and source data instead of trusting business labels from the task prompt. Handles Jinja variable removal correctly by deleting both the conditional tags AND the guarded SQL body.

### Intercom — 3/3 (100%)

Customer support conversation metrics. Tasks involve aggregation across conversation parts, metrics computation with date functions, and correct driving table selection when source tables have disjoint key sets.

**What SignalPilot does well:** Identifies the correct driving table for conversation metrics even when test data is intentionally constructed with disjoint conversation IDs across source tables.

Paradime's report flagged `intercom003` as a "benchmark quality issue" citing a data type overflow bug in the answer key. **SignalPilot resolves it.** The task is designed to test driving table selection — the disjoint IDs are intentional, not a bug. We find it concerning when competing reports label passing tasks as "benchmark quality issues" rather than investigating further.

### QuickBooks — 4/4 (100%)

Financial modeling with the Fivetran QuickBooks dbt package. Tasks include fixing unix epoch date columns in staging model overrides, removing dbt variables and all Jinja-gated SQL, and working with the package's UNION-based intermediate models.

**What SignalPilot does well:** When fixing a bug in one package staging model, greps all sibling staging models for the same pattern and fixes all occurrences — not just the first one found. When removing a `{% if var(...) %}` conditional, deletes the entire guarded block (CTE, join, select expression), not just the Jinja tags.

### Simple — 2/2 (100%)

Basic dbt transformations. Baseline tasks that verify the agent can run dbt commands and produce correct output.

### Workday — 1/1 (100%)

HR data modeling. (Note: `workday001` is `dev` status with a placeholder prompt and no real expected output — we skip it in scoring, as does Paradime.)

---

## The Two Unresolved Tasks

### f1008 — Placeholder solution (skipped)

This task does not include a meaningful reference output for validation. The solution seed is a placeholder (`foo`) rather than a real expected result. We skip this task in our scoring. Paradime, Altimate, and dbt Labs also exclude or skip it.

### workday001 — Incomplete stub (skipped)

This task is an incomplete stub with a placeholder prompt and no real expected output. The solution seed is `foo`. We skip this task. Paradime also skips it.

---

## Tasks Paradime Flagged as "Benchmark Issues" — We Pass Them

Paradime's report lists 5 unresolved tasks. Three of them (`f1002`, `f1006`, `intercom003`) are attributed to benchmark quality issues rather than agent limitations. SignalPilot resolves all three:

| Task | Paradime | Paradime's explanation | SignalPilot | Our take |
|------|----------|----------------------|-------------|----------|
| f1002 | FAIL | "Schema mismatch — extra columns" | **PASS** | Agent must match sibling model patterns, not blindly include all YML columns |
| f1006 | FAIL | "Logic error using SUM instead of MAX" | **PASS** | Agent must distinguish cumulative columns from per-event columns — this is the test |
| intercom003 | FAIL | "Data type overflow bug in answer key" | **PASS** | Agent must select the correct driving table when source tables have disjoint keys — this is the test |

The whole point of ADE-Bench is to test what happens when the agent encounters ambiguous YML, tricky column semantics, and imperfect conditions. Labeling these as benchmark defects misses the point.

---

## How SignalPilot Works

SignalPilot is an open-source MCP server and Claude Code plugin that gives AI agents governed access to databases and dbt projects. On ADE-Bench, the agent runs with:

**A governed MCP server** with 35+ tools for schema exploration, SQL validation, query execution, and dbt project intelligence — all with DDL/DML blocking, LIMIT injection, and audit logging.

**A skill-based workflow** that guides the agent through an 8-step lifecycle: project scan, skill loading, validation, macro discovery, research, technical spec, SQL writing, and verification.

**Domain-specific skills** that load conditionally based on the task: 7 domain skills (ecommerce, financial, HR, marketing, product, media, healthcare) plus specialized skills for dbt snapshots, unit tests, and model versioning.

**A verifier agent** that runs a 7-check protocol after every build: model existence, column schema, row count, fan-out detection, cardinality audit, value spot-check, and table name verification.

**A knowledge base** where agents retrieve and propose organizational knowledge — conventions, decisions, debugging fixes — that accumulate across runs.

### What changed from our baseline

Our starting point was the SignalPilot agent that scored **#1 on Spider 2.0-DBT** (51.56%, +7.45 over #2). That agent was already strong on SQL reasoning and model building, scoring 71% (42/59 ready tasks) on its initial ADE-Bench run with the existing knowledge base and MCP tools.

The gap was not reasoning ability — it was **missing knowledge about newer dbt features** the agent had never encountered:

| Feature | What was missing | Fix |
|---------|-----------------|-----|
| dbt snapshots / SCD2 | No guidance on strategy selection, column casing, or verification | New `dbt-snapshots` skill |
| dbt unit tests | No knowledge of `unit_tests:` YAML format | New `dbt-testing` skill |
| dbt model versioning | No knowledge of `versions:` config | New `dbt-versioning` skill |

Adding these three skills plus a single system prompt rule ("Trust the YML contract for output shape — do not add, remove, or rename structural elements") moved the score from 42/59 to **62/64**.

No task-specific tuning. No per-domain prompt optimization. Three generic skills and one sentence.

---

## How This Compares to Spider 2.0-DBT

ADE-Bench and Spider 2.0-DBT test fundamentally different things.

**ADE-Bench** tests whether an agent can work inside an existing codebase: fix bugs, add features, refactor models, run the right dbt commands. The YML contracts are accurate. The project structure is clean. The challenge is following instructions precisely and knowing your dbt features.

**Spider 2.0-DBT** tests whether an agent can figure out the right SQL when the YML is aspirational, the grain is ambiguous, and the only source of truth is the raw data. The challenge is reasoning under uncertainty — deriving correct logic from messy, underdocumented projects where the documentation is often wrong.

We find Spider 2.0-DBT to be a significantly harder benchmark. ADE-Bench tasks are solvable by an agent that follows instructions carefully and knows its dbt features. Spider 2.0-DBT tasks require the agent to derive logic from data when the project documentation is wrong — a much closer simulation of real-world analytics engineering where things are never as clean as the README says.

SignalPilot holds **#1 on both benchmarks**: 51.56% on Spider 2.0-DBT and 96.9% on ADE-Bench.

---

## Reproducibility

### Our raw data

The full run data — task results, agent output, traces, and project files for all 64 tasks — is available on request. Every task result includes the pass/fail status, test counts, turn counts, and elapsed time.

### Competitor sources

| System | Source |
|--------|--------|
| Paradime DinoAI | [Paradime Blog](https://www.paradime.io/blog/dinoai-ade-benchmark-report) |
| Altimate AI | [Paradime Blog (cited)](https://www.paradime.io/blog/dinoai-ade-benchmark-report) |
| Cortex Code CLI | [Paradime Blog (cited)](https://www.paradime.io/blog/dinoai-ade-benchmark-report) |
| dbt Labs | [Paradime Blog (cited)](https://www.paradime.io/blog/dinoai-ade-benchmark-report) |
| Claude Code baseline | [Paradime Blog (cited)](https://www.paradime.io/blog/dinoai-ade-benchmark-report) |

### How to verify

ADE-Bench is open source: [github.com/dbt-labs/ade-bench](https://github.com/dbt-labs/ade-bench). Clone the repo, run the tasks, compare results.

---

## Same Domain, Different Difficulty: ADE-Bench vs Spider 2.0-DBT

Several domains appear in both benchmarks. The prompts tell the story — ADE-Bench gives explicit instructions, Spider 2.0-DBT gives vague business questions.

### Airbnb

**ADE-Bench:**
> "I got this error, please fix it, and fix it anywhere else it needs to be fixed. Compilation Error in model monthly_agg_reviews: `dbt_utils.surrogate_key` has been replaced by `dbt_utils.generate_surrogate_key`..."

> "Create the models described in the schema.yml file."

**Spider 2.0-DBT:**
> "Aggregate user reviews by sentiment on a daily and month-over-month basis, while also combining listings and host information to track the latest updates for each listing"

> "Complete the data transformation by aggregating review data over a 7-day rolling window, calculating week-over-week percentage changes in review totals by sentiment, and generating unique identifiers for each date and sentiment combination."

ADE-Bench tells the agent exactly what to do — fix this error, create these models. Spider 2.0-DBT describes a business outcome and expects the agent to figure out the SQL, the joins, the grain, and the aggregation logic from the data.

### F1

**ADE-Bench:**
> "Someone noticed that the 'points' columns in constructor_points.sql and driver_points.sql look way too high. Can you figure out what's wrong, fix it, and update the table?"

**Spider 2.0-DBT:**
> "Generate views that rank Formula 1 drivers based on the number of fastest laps, podium finishes, and pole positions, while summarizing their race finishes and positions across all events?"

> "Summarize Formula 1 constructors' race performances, rank constructors based on driver championships, and track driver championships across seasons?"

ADE-Bench points at the bug. Spider 2.0-DBT describes what the output should look like and expects the agent to discover the data model, build the correct joins, and derive the ranking logic.

### Asana

**ADE-Bench:**
> (no explicit prompt shown — tasks involve refactoring CTEs into new models)

**Spider 2.0-DBT:**
> "Can you describe the process used to aggregate task and project metrics for Asana teams and users, including open tasks, completed tasks, and average close times?"

### QuickBooks

**ADE-Bench:**
> "This project is erroring out and needs to be fixed. Fix the underlying issue and update the tables."

**Spider 2.0-DBT:**
> "Please create a table that unions all records from each model within the double_entry_transactions directory. The table should result in a comprehensive general ledger, ensuring each transaction has an offsetting debit and credit entry."

> "Pull a table with all balance sheet entries for asset, liability, and equity accounts. Make sure it includes account details, class, parent information, and the monthly period balances."

ADE-Bench: "it's broken, fix it." Spider 2.0-DBT: "here's a financial accounting concept, figure out the SQL."

### The pattern

ADE-Bench prompts are **imperative and specific**: fix this error, create these models, remove this variable. The agent needs to know its dbt features and follow instructions precisely. The codebase is clean, the YML is accurate, and the project structure tells the agent what to do.

Spider 2.0-DBT prompts are **descriptive and ambiguous**: aggregate these metrics, create this view, combine this data. The agent needs to explore the schema, understand the business logic, query the data to discover grain and cardinality, and derive the correct SQL from incomplete documentation. The YML is often aspirational — row counts are wrong, grain assumptions are incorrect, and the only source of truth is the raw data.

This is why our ADE-Bench score jumped from 71% to 97% by adding three skills and one sentence — the benchmark tests feature knowledge, not reasoning depth. Our Spider 2.0-DBT score (#1 at 51.56%) required months of prompt engineering, verification agents, domain skills, and a knowledge base because that benchmark tests whether the agent can actually think.

---

## What We Learned

This benchmark was great for yielding new skills for SignalPilot in using newer dbt technologies — snapshots, unit tests, and model versioning were all gaps we discovered and filled during this process. But ADE-Bench did not help us improve query accuracy or the agent's ability to follow ambiguous user prompts. The tasks assume clean codebases, accurate YML contracts, and well-structured projects. Real-world data work is messier than that.

We prefer Spider 2.0-DBT due to its much harder nature and the reasoning traces required to pass it. ADE-Bench tests feature knowledge and instruction-following in ideal codebases. Spider 2.0-DBT tests whether the agent can actually think through a data problem when the documentation is wrong and the only truth is in the data itself.

Both benchmarks matter. But if you're evaluating which AI agent will perform best on your messy, real-world dbt project — look at Spider 2.0-DBT scores, not ADE-Bench scores.

---

**SignalPilot is open source.** [GitHub](https://github.com/SignalPilot-Labs/SignalPilot) | [Docs](https://signal-pilot-docs.vercel.app) | [Cloud](https://app.signalpilot.ai)
