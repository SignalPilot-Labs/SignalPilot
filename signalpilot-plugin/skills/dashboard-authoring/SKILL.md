---
name: dashboard-authoring
description: Create, repair, or refine governed SignalPilot dashboards through the run-scoped authoring tools. Use only for explicit dashboard authoring requests, not ordinary analytics questions, chart answers, or HTML reports.
---

# Dashboard Authoring

Keep every authoring decision in this top-level session. Do not invoke `Agent`, a subagent, or another model.

Use authoring contract `2026-09-02.1`. If the skill or matching tools are unavailable, report the setup failure and stop dashboard authoring. Do not use a legacy or hidden fallback.

## Workflow

Write concise user-visible progress only for context resolution, chart drafting, and final assembly. Validation and schema correction are internal work: never narrate individual validation calls or retries.

1. Call `begin_dashboard_authoring` first with the complete request and timezone. For a refinement, pass the exact active `authoring_session_id` from warm context.
2. Use only the returned semantic projection, stable IDs, limits, contract version, and revisions. Never invent explores, fields, metrics, filters, or bindings.
3. For a new dashboard, submit one complete typed plan with `set_dashboard_plan`. Use stable chart, tile, and filter IDs; approved metrics; exact semantic fields; explicit filter mappings; required flags; and non-overlapping layout intent. `visualization` is a string. Filters belong only in `plan.filters`; intents reference them through `shared_filter_ids`.
   Before submitting the plan, inspect every `line` or `area` intent. Each one must include a governed date/timestamp dimension and reference an applicable bounded date filter through `shared_filter_ids`. The filter must target that intent's explore directly or through its `tileTargets` entry. Never submit a time-series plan first and add its required window in a repair call.
4. Construct chart payloads from the exact tool schema and canonical shapes below before calling any chart tool. Never use tool failures to discover the payload shape. Once every chart has the same proven structural contract, up to five independent initial `upsert_dashboard_chart` calls may run concurrently. Completion order must not change IDs, plan order, or the final result.
5. When governed semantic validation rejects one chart, preserve every ready chart, use only the returned safe issues and allowed alternatives, then retry that chart once without user-visible narration. Do not retry it a second time. An input-schema error means the loaded contract was not followed: correct the exact JSON path once and never fan out that invalid shape.
6. Use `apply_dashboard_operations` for bounded stable-ID refinements, shared filters, layout, names, descriptions, or interaction wiring. On follow-up turns, change only what the user requested and leave unrelated charts intact.
7. Call `create_dashboard_preview` only after every required chart is ready and any requested operations validate. Pass the exact current plan and draft revisions.
8. Tell the user the private preview is ready for review and requires explicit Apply. Never claim it was saved, applied, shared, published, archived, or deployed.

## Exact payload shapes

Use the complete JSON Schema loaded with each tool as the authority. These fragments highlight the easy-to-confuse boundaries; replace every placeholder with an exact value returned by `begin_dashboard_authoring`.

Plan intents use snake_case and a scalar visualization:

```json
{
  "chart_id": "revenue-kpi",
  "tile_id": "revenue-kpi-tile",
  "label": "Total revenue",
  "question": "What is total revenue?",
  "description": "Total governed revenue",
  "required_concepts": ["revenue"],
  "explore_name": "<explore name>",
  "dimensions": [],
  "metrics": ["<metric field ID>"],
  "section": "Overview",
  "order": 0,
  "layout": {"x": 0, "y": 0, "w": 12, "h": 4},
  "visualization": "kpi",
  "shared_filter_ids": ["date-window"],
  "required": true
}
```

A bounded relative date filter uses `values` plus `settings`, never `value`, `default_value`, `field_id`, `filter_bindings`, or per-intent `time_window`:

```json
{
  "id": "date-window",
  "operator": "inThePast",
  "values": [90],
  "target": {"tableName": "<explore name>", "fieldId": "<date field ID>"},
  "tileTargets": {
    "<other tile ID>": {"tableName": "<other explore>", "fieldId": "<other date field ID>"}
  },
  "label": "Date range",
  "settings": {"unitOfTime": "days", "completed": true}
}
```

Every semantic chart query is flat under `query`; use `filters: {}`, plural `sorts`, and exact camelCase field names:

```json
{
  "kind": "semantic",
  "exploreName": "<explore name>",
  "dimensions": ["<dimension field ID>"],
  "metrics": ["<metric field ID>"],
  "filters": {},
  "sorts": [{"fieldId": "<metric field ID>", "descending": true}],
  "limit": 10,
  "projectId": "<project ID>",
  "commitSha": "<commit SHA>"
}
```

Visualization configurations are exactly one of:

```json
{"type": "big_number", "config": {"field": "<metric field ID>"}}
{"type": "table", "config": {"columns": ["<dimension field ID>", "<metric field ID>"]}}
{"type": "cartesian", "config": {"seriesType": "bar", "layout": {"xField": "<dimension field ID>", "yField": ["<metric field ID>"]}}}
```

Every chart uses `signalPilot.crossFilter` as a boolean and a non-empty provenance reference:

```json
{"crossFilter": false, "provenanceRef": "<stable chart or verification reference>"}
```

Do not emit Vega-Lite `mark` or `encoding`, nested `semantic`, nested `big_number`/`table`/`cartesian`, `sort`, `explore`, `required_concepts`, or any undeclared key in a chart payload.

## Fail closed

- A partial draft may remain visible, but do not finalize it while a required chart is missing or failed.
- Custom SQL is low confidence. It requires the existing explicit user confirmation before preview execution.
- Never bypass a validation issue by changing the contract version, session, project binding, commit, connection, or stable ID.
- Never apply or discard a dashboard through these tools. Those actions belong to the user-facing preview UI.
- Do not automatically load `dbt-workflow` or run exploratory queries. Use governed schema or dbt tools only when the user explicitly asks for investigation that the bounded projection cannot answer.

## Privacy

Do not expose the authoring session ID, internal revisions, payload hashes, raw JSON, prompts, SQL or parameters, result rows, credentials, internal identifiers, stack traces, or hidden reasoning. User-visible progress should contain business labels and safe outcomes only.
