---
name: dashboard-authoring
description: Create, repair, or refine governed SignalPilot dashboards through the run-scoped authoring tools. Use only for explicit dashboard authoring requests, not ordinary analytics questions, chart answers, or HTML reports.
---

# Dashboard Authoring

Keep every authoring decision in this top-level session. Do not invoke `Agent`, a subagent, or another model.

Use authoring contract `2026-09-02.1`. If the skill or matching tools are unavailable, report the setup failure and stop dashboard authoring. Do not use a legacy or hidden fallback.

## Workflow

Before each major group, write one concise user-visible progress sentence. Do this before context resolution, planning, chart drafting, a validation repair, and final assembly.

1. Call `begin_dashboard_authoring` first with the complete request and timezone. For a refinement, pass the exact active `authoring_session_id` from warm context.
2. Use only the returned semantic projection, stable IDs, limits, contract version, and revisions. Never invent explores, fields, metrics, filters, or bindings.
3. For a new dashboard, submit one complete typed plan with `set_dashboard_plan`. Use stable chart, tile, and filter IDs; approved metrics; exact semantic fields; explicit filter mappings; required flags; and non-overlapping layout intent.
4. Submit each independent initial chart with `upsert_dashboard_chart`. Up to five chart calls may run concurrently. Completion order must not change IDs, plan order, or the final result.
5. When one chart is rejected, preserve every ready chart. Narrate the correction, use only the returned safe issues and allowed alternatives, then retry that chart once. Do not retry it a second time.
6. Use `apply_dashboard_operations` for bounded stable-ID refinements, shared filters, layout, names, descriptions, or interaction wiring. On follow-up turns, change only what the user requested and leave unrelated charts intact.
7. Call `create_dashboard_preview` only after every required chart is ready and any requested operations validate. Pass the exact current plan and draft revisions.
8. Tell the user the private preview is ready for review and requires explicit Apply. Never claim it was saved, applied, shared, published, archived, or deployed.

## Fail closed

- A partial draft may remain visible, but do not finalize it while a required chart is missing or failed.
- Custom SQL is low confidence. It requires the existing explicit user confirmation before preview execution.
- Never bypass a validation issue by changing the contract version, session, project binding, commit, connection, or stable ID.
- Never apply or discard a dashboard through these tools. Those actions belong to the user-facing preview UI.
- Do not automatically load `dbt-workflow` or run exploratory queries. Use governed schema or dbt tools only when the user explicitly asks for investigation that the bounded projection cannot answer.

## Privacy

Do not expose the authoring session ID, internal revisions, payload hashes, raw JSON, prompts, SQL or parameters, result rows, credentials, internal identifiers, stack traces, or hidden reasoning. User-visible progress should contain business labels and safe outcomes only.
