---
name: dbt-knowledgebase
description: "Populate the knowledge base from dbt project research. Proposes entries across all 6 categories at org, project, and connection scopes."
disable-model-invocation: false
allowed-tools: Bash(dbt *) Bash(python3 *)
---

# dbt Knowledge Base Generator

## Purpose

Populate the knowledge base with structured entries from your research.
After completing exploration (Steps 1-5 of the workflow), propose entries
across ALL categories and scopes below. Every category MUST have at least
one entry after this step - even if it is an initial summary based on what
you observed.

## Knowledge Categories

### understanding - The onboarding doc

Scope: `org` AND `project`. Always loaded at the start of every run.

The 30-second briefing a new analyst needs before touching anything.

**At org level** (`scope="org"`): company terminology, fiscal calendar,
universal join keys, database engine. If no org-level understanding exists,
create one summarizing what you can infer from this project - the database
type, general data domain, naming patterns.

**At project level** (`scope="project"`): what the pipeline models, key
entities, data flow, how many models, what the task is about.

Example: "This project models Reddit post and comment data from paranormal
subreddits. Two mart models join posts to comments via post URL. Source
data is in DuckDB with 3 raw tables."

### conventions - The style guide

Scope: `org` AND `project`. Always loaded alongside understanding docs.

How this team writes SQL and organizes models. Not data facts - patterns
about how to work with data.

**At org level**: database-wide SQL patterns (e.g., materialization
strategy, column casing). If nothing exists, create one from what you
observe in this project's existing models.

**At project level**: project-specific patterns from sibling models -
JOIN types used, aggregation functions, column naming prefixes/suffixes,
macro usage patterns, how existing models handle NULLs.

Example: "All sibling models use LEFT JOIN for dimension tables." /
"Macro extract_hour(col) produces hour_<col> - used in existing models."

### decisions - The "why" behind a model

Scope: `project` only. Searchable by sub-agents.

Per-model reasoning from your research. Why this grain, why this driving
table, why this join type, why this filter. Document the reasoning that
saves the next agent from re-deriving the same logic.

One entry per model or per significant cross-model decision.

Example: "prod_posts_ghosts drives from stg_reddit_posts (250 rows).
LEFT JOIN not needed - single source model, no joins." /
"Join path between posts and comments is post_url, not post_id -
post_id format differs between tables (t3_ prefix in comments)."

### domain-rules - Business logic

Scope: `org` or `project`. Searchable by sub-agents.

Business rules encoded in the data that you cannot discover from schema
alone. These come from column values, status flags, data patterns.

Example: "comment score can be negative (downvoted)." /
"NULL post text means link-only post, not missing data." /
"l_returnflag values: A=accepted, N=new, R=returned."

### debugging - Known errors and fixes

Scope: `project` only. Searchable when agent hits errors.

Hard-won lessons from exploration - errors encountered during validation,
parse issues, data quality problems found.

Example: "dbt parse warns about 36 unused config paths - safe to ignore." /
"DuckDB BIGINT overflow on SUM of large integers - cast to DOUBLE."

### quirks - Database-specific surprises

Scope: `connection` only. Loaded when working with that connection.

Tied to a specific database instance. Data type mismatches, unexpected
NULLs, format oddities.

Example: "post_id in comments has t3_ prefix but posts table has bare
integer IDs." / "price column stores costs as negative values."

## Proposal Checklist

After research, create a task for EACH category below. Mark each
`in_progress` when you start proposing for that category and `completed`
when done.

1. **org:understanding** - Create or verify org-level onboarding doc
2. **org:conventions** - Create or verify org-level SQL patterns
3. **project:understanding** - Create project overview doc
4. **project:conventions** - Document sibling model patterns, macros
5. **project:decisions** - Document per-model research findings
6. **project:domain-rules** - Document business logic from data
7. **project:debugging** - Document any errors or warnings found
8. **connection:quirks** - Document data oddities for this database

For each category: call `search_knowledge` first to check if an entry
already exists. If it does, skip it. If it does not, propose one.

## Proposal Format

```
propose_knowledge(
  scope="project",
  scope_ref="<project_name>",
  category="decisions",
  title="<short-kebab-case-slug>",
  body="<detailed body with evidence>"
)
```

For org-level entries, use `scope="org"` and `scope_ref=None`.
For connection-level entries, use `scope="connection"` and
`scope_ref="<connection_name>"`.

Titles MUST be lowercase kebab-case slugs.

Body MUST include:
- WHAT: the observation or fact
- EVIDENCE: specific table, column, query result, or file

The body MUST be purely descriptive. State what EXISTS, not what to DO.

BAD IMPACT (prescriptive): "Do not add macro columns unless YML lists them."
GOOD (descriptive): "Macros produce hour_created_at and normalized_created_at
columns. These columns are not in the current YML contract."

The reader (a future builder agent) decides what to do with the fact.
You only document what you found.

## Category names — server enum

The gateway's canonical categories are **`context`, `decisions`, `rules`,
`troubleshooting`** (`gateway/models/knowledge.py`). The six names used above
(understanding, conventions, decisions, domain-rules, debugging, quirks) are
legacy and map onto the canonical four on write (understanding→decisions,
conventions/domain-rules→rules, debugging/quirks→troubleshooting). Prefer the
canonical four when the server accepts them; if a propose call is rejected for
an unknown category, retry with the canonical name.

## Body formatting — entries render as markdown

The KB UI renders entry bodies as **markdown**. Plain prose full of SQL
identifiers breaks the renderer: mid-word underscores italicize across words,
`__c` suffixes read as bold markers, and bare `||` / `|` characters mangle
lines. Every body MUST be markdown-safe:

1. Wrap EVERY table, column, model, and identifier in backticks:
   `days_quoted__c`, `user_pseudo_id || ':' || ga_session_id`.
2. Wrap SQL fragments and expressions in code spans; multi-line SQL goes in
   fenced code blocks.
3. Use bold labels (`**What:**`, `**Why:**`, `**Evidence:**`,
   `**Alternatives rejected:**`, `**Verification:**`) instead of ALLCAPS
   prose labels; break list-like prose into bullet or numbered lists.
4. Never leave `_`, `__`, `|`, `||`, or `*` bare outside a code span.
   Dollar figures and percentages stay plain text.

## Content bar — what earns a KB entry

Prioritize knowledge a future agent CANNOT easily derive from the code or
comments:

- **Ground truths**: exact approved totals/counts and the definitions that
  produce them (e.g. a finance-approved revenue definition with its number).
- **External/business knowledge**: what a flag means operationally, how the
  business runs, vocabulary crosswalks between systems.
- **Mart-specific caveats**: known issues, superseded models, which columns
  of a mart to trust and which not to.
- **Decision history**: the decisions made while building each model — what
  was chosen, alternatives rejected, the verification numbers that settled
  it, follow-ups deferred — and user corrections, written as dated decision
  entries ("Dan reviewed the draft and corrected the approach: …").

Plain restatements of what the SQL already shows are low-value; the reader
can open the model. Facts that live only in data values, in conversations,
or in verification runs are what the KB is for.

## Rules

- NEVER write SQL files or run dbt build commands
- NEVER modify .yml files
- NEVER propose negative claims ("X is not used", "not needed")
- NEVER write instructions in entries ("Do not", "Always", "Use X")
 - state facts only, let the reader decide
- ALWAYS check if entry exists before proposing (avoid duplicates)
- ALWAYS include EVIDENCE in the body
- Every category MUST have at least one entry after this step
- STOP after all 8 checklist items are completed
