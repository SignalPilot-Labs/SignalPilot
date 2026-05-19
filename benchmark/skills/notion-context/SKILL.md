---
name: notion-context
description: "Gather business context from Notion before dbt builds. Searches pages, extracts definitions/decisions/constraints, writes structured context for the build agent and notion-verify subagent."
---

# Notion Context Skill

Gather business context from Notion using SignalPilot's governed Notion tools.

## 1. Find the Integration

Call `list_database_connections` — this also lists Notion integrations. Pick
the integration to use:

- If the user named one in the task instruction, use that.
- If only one Notion integration exists, use it.
- If multiple exist and none was specified, list them and ask the user.
- If none exist, skip — Notion context is optional. Do not block the workflow.

Verify the integration works with a test search:

```
notion_search
  integration_name: "<name>"
  query: "test"
```

Save the working `integration_name` for all subsequent calls.

## 2. Search

Extract keywords from the task instruction — table names, metric names, business
terms not defined in YML.

```
notion_search
  integration_name: "<name>"
  query: "<keywords>"
```

**No results?** Try in order:
1. Broader keywords ("daily shop orders" -> "orders")
2. Synonyms ("revenue" -> "sales")
3. Individual terms

If still nothing -> write `No relevant Notion context found.` to
`notion_context.md` (include the `# Integration:` header) and return.

## 3. Fetch and Navigate

For each matching page (up to 5):

```
notion_fetch_page
  integration_name: "<name>"
  page_id: "<id>"
```

**If the page lists child pages but has no content** — it's a container page.
Fetch the child pages that look relevant to the task (by title). Meeting notes
and transcripts are typically one level down from the container.

**If the page has content** — extract from it directly.

## 4. Extract Context

Scan page content for three categories:

| Category | Signal phrases | Example |
|---|---|---|
| **DEFINITION** | "X means Y", "X is defined as", "X = Y" | "active customer = 1+ orders in 90 days" |
| **DECISION** | "we decided", "agreed to", "going with" | "grain is (shop_id, date)" |
| **CONSTRAINT** | "exclude", "only include", "must filter" | "exclude test orders where source = 'internal'" |

For each item record:
- Verbatim excerpt (under 200 chars) or paraphrase
- Source page title and ID
- Category tag (DEFINITION / DECISION / CONSTRAINT)

Check for **contradictions** between items. If two sources disagree, flag both
with `CONFLICT:`. Do NOT silently pick one.

## 5. Write Context File

Write `notion_context.md` in the working directory:

```
# NOTION CONTEXT
# Integration: <integration_name>
# Task: <task summary>
# Sources: <N> pages searched, <M> items extracted

## DEFINITIONS
- [DEF-1] "<term>" = <definition>
  Source: <page_title> — https://notion.so/<page_id>

## DECISIONS
- [DEC-1] <decision statement>
  Source: <page_title> — https://notion.so/<page_id>

## CONSTRAINTS
- [CON-1] <constraint>
  Source: <page_title> — https://notion.so/<page_id>

## CONFLICTS
- <item A> (from <page_A>) vs <item B> (from <page_B>)

## SOURCES CONSULTED
- <page_title> — https://notion.so/<page_id> — <N> items extracted
```

Each item gets a stable ID (DEF-1, DEC-1, CON-1, etc.) so the verify agent can
reference them in the traceability matrix. This file is read by the notion-verify
subagent after the build.

## 6. Return to Agent

Return DEFINITIONS, DECISIONS, and CONSTRAINTS to the calling agent. The agent
MUST:
- Reference items when making grain, join, filter, and column decisions
- Write `-- NOTION: [DEF-1] <brief reason>` comments in SQL for every decision
  influenced by Notion context. Use the item ID from `notion_context.md`.
- Flag CONFLICT items and explain which side was chosen

## Rules

- NEVER fabricate context. No Notion source = no context item.
- NEVER block the workflow on missing context. It's supplementary.
- NEVER silently resolve conflicts. Flag them.
