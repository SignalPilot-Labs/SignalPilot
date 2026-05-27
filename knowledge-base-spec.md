# SignalPilot Knowledge System (SKS)

## Overview

An RLM-inspired knowledge system where SignalPilot agents build, share, and refine organizational data knowledge over time. Agents propose knowledge entries after each run; entries flow through an approval gate (auto or human) into a shared, versioned knowledge base that future runs retrieve from.

References:
- [Recursive Language Models (MIT, arXiv 2512.24601)](https://arxiv.org/abs/2512.24601) — agents manage their own context via Python REPL + sub-LLM calls
- [MemRL](https://arxiv.org/abs/2601.03192) — episodic memory + RL for high-utility strategy filtering
- [Memory-R1](https://arxiv.org/abs/2508.19828) — structured memory operations (ADD/UPDATE/DELETE) learned via RL
- Aider Architect/Editor split — separate reasoning from execution (85% benchmark)
- Devin 2.0 — persistent memory across long-running tasks

## Architecture

```
┌─────────────────────────────────────────────────────┐
│  LAYER 1: EXPLORATION                                │
│  Project scan, skill loading, blueprint tool         │
│  Output: raw data about the project                  │
└──────────────────────┬──────────────────────────────┘
                       │
                       ▼
┌─────────────────────────────────────────────────────┐
│  LAYER 2: COMPRESSION (technical_spec.md)            │
│  Agent distills exploration into structured decisions │
│  Persists on disk — retries skip exploration          │
└──────────────────────┬──────────────────────────────┘
                       │
                       ▼
┌─────────────────────────────────────────────────────┐
│  LAYER 3: EXECUTION                                  │
│  Write SQL from spec, build, verify                  │
│  On verify FAIL: update spec first, then re-execute  │
└──────────────────────┬──────────────────────────────┘
                       │
                       ▼
┌─────────────────────────────────────────────────────┐
│  LAYER 4: REFLECTION (knowledge entries)             │
│  Agent proposes entries after run completion          │
│  Entries flow through approval gate into shared base  │
│  Future runs retrieve relevant entries before Layer 2 │
└─────────────────────────────────────────────────────┘
```

## Knowledge Entry Model

```yaml
id: uuid
scope: org | project | connection
category: convention | schema | decision | domain_rule | debugging
title: "Revenue excludes returns and tax"
body: |
  When computing revenue metrics in this project, exclude rows where
  order_status = 'returned'. The returns table (stg_returns) is separate
  from orders, so filtering happens via LEFT JOIN exclusion, not WHERE
  clause on the orders table.
source_run: run_id          # which run proposed this
confidence: confirmed | proposed | disputed
confirmed_by: [user_ids] | "auto"
created_at: timestamp
updated_at: timestamp
tags: [revenue, returns, ecommerce]
supersedes: [entry_id]      # replaces older entry (version chain)
```

### Scoping

- **org-level**: shared by everyone in the organization (e.g., "customer_id is always VARCHAR", "fiscal year starts April 1")
- **project-level**: shared within a dbt project (e.g., "orders.status values: pending, shipped, delivered, returned, cancelled")
- **connection-level**: specific to a database connection (e.g., "raw_orders has 2.3M rows", "l_returnflag: A=accepted, N=new, R=returned")

### Categories

- **convention**: team norms and patterns ("we always use LEFT JOIN for dim tables", "revenue excludes tax")
- **schema**: discovered data facts ("orders has 5 status values", "customer_id is VARCHAR(36)")
- **decision**: reasoning about a specific modeling choice ("chose LEFT JOIN for dim_products because some products have no sales")
- **domain_rule**: business logic ("returns within 30 days get full refund, after 30 days get store credit")
- **debugging**: solutions to recurring problems ("DuckDB BIGINT overflow on SUM — cast to DOUBLE first")

## Approval Gate

### Auto-approve mode (default)
- Agent proposes entry -> immediately added with `confidence: proposed`
- If 3+ successful runs reference the same knowledge -> auto-promotes to `confirmed`
- If a run contradicts it -> flags as `disputed`, surfaces to user

### Human-approve mode (enterprise)
- Agent proposes entry -> goes to approval queue
- Any team member can: approve, edit, reject, or merge with existing
- Approved entries become `confirmed`
- Rejected entries are discarded (agent won't re-propose the same thing)

### Toggle
Per-org default with project-level override:
```
Org default: auto-approve
  project "revenue-pipeline": human-approve (sensitive)
  project "sandbox-exploration": auto-approve (low risk)
```

## Poisoning Prevention

1. **Confidence scoring** — proposed entries carry less weight than confirmed in retrieval ranking
2. **Contradiction detection** — new entry contradicting a confirmed entry is auto-flagged `disputed` regardless of approval mode
3. **Staleness** — schema entries (row counts, distinct values) expire after configurable TTL and get re-verified on next run
4. **Source tracking** — every entry links to the run that proposed it; bad entries are traceable and reversible
5. **Supersession** — new entries explicitly replace old ones; version history preserved; rollback possible
6. **Human override always wins** — human edits are `confirmed` immediately and cannot be auto-overridden by agent proposals

## Retrieval

Before writing the spec (Layer 2), the agent calls:

```
retrieve_knowledge(connection_name, project_dir, task_description)
```

Returns relevant entries ranked by:
1. Scope match (project-level > org-level for that project)
2. Category relevance (schema for research, convention for writing)
3. Confidence (confirmed > proposed > disputed)
4. Recency (newer entries ranked higher)

Returns top 5-10 entries, injected into agent context before spec writing.

## Technical Spec (Layer 2 — Phase 1 Implementation)

The per-run spec doc written by the agent after exploration. This is the immediate deliverable; the knowledge base layers on top later.

### File: `<project_dir>/technical_spec.md`

```markdown
# Technical Spec: <task_name>

## Build Order
1. model_a (staging — build first)
2. model_b (mart — depends on model_a)

## Model: model_a
- Driving table: source_table (N rows)
- Joins: other_table ON key = key (LEFT JOIN)
- Key expressions:
  - computed_col = ROUND(price * (1 - discount), 2)
  - status_col = raw_flag
- Status filter: none at this layer
- Expected grain: one row per line item
- Expected rows: N

## Model: model_b
- Source: ref('model_a') WHERE status_col != 'excluded_value'
- NOT from raw tables (model_a already computes what we need)
- Grain: one row per entity (aggregate)
- Key expressions:
  - total_metric = SUM(computed_col)  [reuse from model_a]
- Expected rows: ~N (from blueprint entity count)

## Decisions
- model_a computes computed_col -> downstream refs it, does not recompute
- Exclusion filter applied in downstream, not in staging
- Sibling pattern: uses COUNT(*) not COUNT(DISTINCT)
```

### Spec rules
- **Mandatory fields per model**: driving table, joins, source (ref or raw), key expressions, expected grain
- **Decisions section**: explicit reasoning about ref-reuse, filter placement, grain choices
- **NOT in spec**: full SQL (that's execution), raw blueprint output (that's exploration), domain knowledge (that's in skills)

### Retry behavior
- Agent checks if `technical_spec.md` exists at start of Step 5.5
- If exists: read it, skip Steps 4-5, go straight to Step 6
- If verifier fails: update the spec first, then rewrite SQL from updated spec

## UI (Phase 3)

```
+----------+----------------------------------------------+
| Projects |  revenue-pipeline / Conventions               |
|  +- rev  |                                              |
|  +- mktg |  +-----------------------------------+       |
|  +- hr   |  | Revenue excludes returns          |       |
|          |  | confirmed - 3 runs - @alice        |       |
| Org-wide |  |                                   |       |
|  +- conv |  | In this project, revenue calcs    |       |
|  +- schema| | exclude rows where order_status   |       |
|  +- debug|  | = 'returned'...                   |       |
|          |  |                                   |       |
| Pending  |  | [Edit] [Archive] [Dispute]        |       |
|  +- 3    |  +-----------------------------------+       |
|          |                                              |
| [+ New]  |  Related: schema/orders-status-values        |
+----------+----------------------------------------------+
```

Team members can:
- Browse by project, category, or tag
- Edit entries (wiki-style, version history)
- Create entries manually (not just agent-proposed)
- Link entries to each other
- Search across all knowledge
- See which runs used which knowledge entries

## Implementation Phases

### Phase 1 — Technical Spec (now)
- Add Step 5.5 to dbt-workflow: agent writes `technical_spec.md` after blueprint
- On retries: agent reads existing spec, skips re-exploration
- Naming and structure designed to translate into knowledge entries later
- No persistence beyond the project directory

### Phase 2 — Knowledge Base Backend (product v1)
- Knowledge entries stored in SignalPilot API (PostgreSQL)
- `retrieve_knowledge` MCP tool for agent retrieval
- `propose_knowledge` MCP tool for agent proposals
- Auto-approve mode only
- Entries visible in agent run traces (no dedicated UI yet)

### Phase 3 — Knowledge Base UI (product v2)
- Dedicated page in SignalPilot web app
- Obsidian-like browsing, editing, linking
- Approval queue for human-approve mode
- Team collaboration features
- Search and filtering

### Phase 4 �� RLM Loop (future)
- Track which knowledge entries correlate with successful runs
- Retrieval ranking improves over time (entries that help pass get boosted)
- Agent learns which categories of knowledge to propose
- Specs + traces + eval results become RL training data
- The agent learns to write better specs natively (the MIT RLM loop)

## Token Budget (Phase 1)

| Step | First run | Retry (spec exists) |
|------|-----------|---------------------|
| Steps 1-3 (scan, skills, validate) | ~2K | ~2K |
| Steps 4-5 (macros, blueprint) | ~3K | SKIP |
| Step 5.5 (write spec) | ~500 | SKIP (read ~300) |
| Step 6 (write SQL) | ~4K | ~3.5K |
| Step 7 (verify) | ~3K | ~3K |
| **Total** | ~12.5K | ~8.8K |

Retry saves ~30% of tokens by skipping exploration and reading the compressed spec instead.
