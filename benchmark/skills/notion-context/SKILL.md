---
name: notion-context
description: "Load at dbt workflow Step 0 to gather business context from Notion. Searches configured pages, extracts decisions/definitions/constraints, verifies relevance, returns structured context block."
type: skill
---

# Notion Context Skill — Gather, Verify, Report

Three phases: **gather** context from Notion, **verify** it applies to the
current task, **report** structured output for the agent and the notion-verify
subagent.

## 1. Load Config

Read `.claude/notion-config.md` in the working directory.

**If missing or incomplete** → tell user to run `/notion-setup` (one-time:
connects Notion MCP, configures search scope and report page). STOP.

**If valid** → parse:
- `SEARCH_PAGE_IDS` — root pages whose children are searchable
- `VERIFICATION_PAGE_ID` — report destination (used by notion-verify subagent)

## 2. Gather — Build Search Index

For each ID in `SEARCH_PAGE_IDS`, call `notion-fetch` with `id: "<page_id>"`.
Collect all child page IDs and titles. This is the search universe — discard
anything outside it.

## 3. Gather — Search

Extract keywords from the task instruction and any ambiguous business terms
not resolved by YML.

```
notion-search
  query: "<keywords>"
  filter: { "object": "page" }
```

Cross-reference results with the search universe from Section 2. Keep only
matches within configured scope.

**No results?** Try in order:
1. Broader keywords (drop qualifiers: "daily shop orders" → "orders")
2. Synonyms ("revenue" → "sales", "customer" → "user")
3. Individual term searches

If still nothing → write `No relevant Notion context found.` to
`notion_context.md` and return. Missing context is not a blocker.

## 4. Gather — Fetch and Extract

For each matching page (up to 5), call `notion-fetch` with `id: "<page_id>"`.

Extract into three categories:

| Category | Signal phrases | Example |
|---|---|---|
| **DEFINITION** | "X means Y", "X is defined as", "X = Y" | "active customer = 1+ orders in 90 days" |
| **DECISION** | "we decided", "agreed to", "going with" | "grain is (shop_id, date)" |
| **CONSTRAINT** | "exclude", "only include", "must filter", "never" | "exclude test orders where source = 'internal'" |

For each extracted item, record:
- Verbatim excerpt (under 200 chars) or paraphrase (longer passages)
- Source page title
- Source page ID
- Date (from title or properties, if available)

## 5. Verify — Relevance Check

For each extracted item, assess whether it applies to the current task:

| Relevance | Criteria | Action |
|---|---|---|
| **DIRECT** | Names a table, column, or metric in the current task | Include, mark as DIRECT |
| **RELATED** | Same domain/entity but doesn't name specific objects | Include, mark as RELATED |
| **UNRELATED** | Different domain, no connection to the task | Discard |

Also check for **contradictions** between items. If two sources disagree on
the same topic (e.g. different grain definitions), flag both with
`CONFLICT: <item A> vs <item B>`. Do NOT silently pick one.

## 6. Report — Write Structured Context

Write `notion_context.md` in the working directory with the full context block:

```
# NOTION CONTEXT
# Task: <task instruction summary>
# Sources: <N> pages searched, <M> items extracted
# Generated: <YYYY-MM-DD HH:MM UTC>

## DEFINITIONS
- [DIRECT] "<term>" = <definition>
  Source: <page_title> (<date>) — https://notion.so/<page_id>

## DECISIONS
- [RELATED] <decision statement>
  Source: <page_title> (<date>) — https://notion.so/<page_id>

## CONSTRAINTS
- [DIRECT] <constraint>
  Source: <page_title> (<date>) — https://notion.so/<page_id>

## CONFLICTS
- <item A> (from <page_A>) vs <item B> (from <page_B>)
  Resolution: <none — flag for human review>

## SOURCES CONSULTED
- <page_title> (<date>) — https://notion.so/<page_id> — <N> items extracted
- <page_title> (<date>) — https://notion.so/<page_id> — 0 items (no relevant content)
```

This file is read by the notion-verify subagent after the build for the
traceability report.

## 7. Report — Return to Agent

Return the DEFINITIONS, DECISIONS, and CONSTRAINTS sections to the calling
agent's working memory. The agent MUST:
- Reference DIRECT items when making grain, join, filter, and column decisions
- Note RELATED items as supporting context
- Flag CONFLICT items and explain which side was chosen and why
- Write `-- NOTION: <source>` comments in SQL for decisions influenced by context

## When to Load

- **dbt workflow Step 0** — always, before `dbt_project_map`. Even "no results"
  gets logged to `notion_context.md`.
- **Mid-workflow** — if the agent hits ambiguity (undefined business term,
  unclear grain, conflicting sibling patterns) and the initial search missed
  relevant context, re-run Sections 3–7 with more specific keywords.

## Rules

- NEVER fabricate context. No Notion source = no context item.
- NEVER block the dbt workflow on missing context. It's supplementary.
- NEVER silently resolve conflicts. Flag them.
- Verbatim excerpts for items under 200 chars. Paraphrase longer passages.
