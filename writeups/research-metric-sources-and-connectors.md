# Research: Where Metrics Live + Connector Aggregation Layer

*Deep-research run 2026-07-23 (103 agents; 21 sources; 25 claims 3-vote adversarially
verified — 22 confirmed, 3 refuted). Question from Dan: validate the metric-scatter
hypothesis (dashboards / notebooks / Notion / GDocs / Slack / dbt / warehouse) and find
an open-source connector aggregator we can embed to automate onboarding.*

## Q1 — Where do metric definitions actually live?

**Verdict: the hypothesis is qualitatively validated; nobody has quantified it.**

- **No survey provides a location breakdown** (confirmed 6-0). dbt's State of Analytics
  Engineering (2025 + 2026) measures *symptoms* — 53% cite poor data quality, 41%
  ambiguous data ownership, trust/AI-governance gaps — but never asks "where are your
  KPIs defined". Nothing from Gartner/vendors either. If we want the number, we'd have
  to run our own practitioner survey (which is itself a content/GTM opportunity).
- **The strongest evidence is first-party practitioner testimony** (confirmed 9-0):
  Airbnb pre-Minerva — Data Science and Finance gave the CEO *different answers to the
  same question* because definitions were embedded in "slightly different tables,
  metric definitions, and business logic"; derived tables sprouted "every other day"
  with no dedup. Their fix, Minerva ("define once, use everywhere"), grew to **12,000+
  metrics, 4,000 dimensions, 200+ data producers** — one company's definition surface.
- Untested tiers from the hypothesis (no surviving evidence either way): notebooks,
  Google Docs/Confluence, Slack-thread prevalence. The scatter across BI + dbt +
  warehouse SQL is well-evidenced; the docs/chat tier remains anecdotal.

## Q2 — Is there an embeddable connector aggregator? **Yes: DataHub ingestion.**

### Recommendation: `acryl-datahub` (DataHub's ingestion framework) as the backbone

| Axis | Finding (all 3-0 verified) |
|---|---|
| License | **Genuinely Apache-2.0** (PyPI SPDX + repo LICENSE + setup.py agree) — clean for commercial closed-source embedding. Actively maintained (release 2026-07-16). |
| Embeddability | pip-installable **Python library**, runs fully in-process (`Pipeline.create(dict)`, documented "as-a-library" mode) — no DataHub server/UI needed; file/console/datahub-lite sinks require no backend, so we **repoint the sink into our knowledge base**. |
| Coverage | Extras verified against PyPI metadata: **snowflake, bigquery, redshift, databricks (Unity Catalog), dbt, looker, tableau, powerbi, superset, metabase (both Certified), postgres — plus `notion` and `slack`**. That is our entire target list except Google Docs/Drive. |

Refuted assumption worth noting: an early claim that DataHub *lacks* Notion/Slack lost
0-3 — the extras exist (caveat: the slack extra is metadata-oriented, user/channel
resolution more than thread content).

### The rest of the field

- **dlt (dlthub)** — Apache-2.0, plain-Python sources vendored via `dlt init`,
  explicitly designed to be customized, zero server. **Complementary, not sufficient**:
  covers Notion + Slack *content* well, but has **no BI/dbt/warehouse-metadata
  connectors at all**. Good supplement where we need deeper docs/chat content than
  DataHub's metadata-level extras.
- **Airbyte** — ELv2 core, and the "connectors are still MIT" belief was **refuted
  0-3** (maintained connectors moved to ELv2 in 2024). Embedding for customer data
  movement is explicitly permitted by their FAQ (only reselling-as-ELT / exposing
  their UI/API is barred) — legally workable but needs counsel review, and it's a
  server platform, operationally heavy vs an in-process library.
- **OpenMetadata** — pip-installable with 80+ connectors, BUT its workflow schema
  **hard-requires a running OpenMetadata server (JWT sink)**, and recent releases
  carry the **Collate Community License** instead of Apache. Disqualified.
- **Not evaluated by surviving claims** (open questions): Amundsen databuilder,
  Singer/Meltano, CloudQuery, Estuary, Nango, Composio, Panora, MCP server
  collections. MCP angle observed in sources: official Notion MCP server, Looker MCP
  (Google), Snowflake Cortex MCP exist — relevant as *agent-time* access rather than
  batch onboarding ingestion, and we already speak MCP.

### What we'd still build in-house
1. **Google Docs/Drive connector** — absent from every framework evaluated.
2. **The definition-extraction/normalization layer** — turning ingested LookML,
   dashboard metadata, dbt metrics, and doc pages into KB entries (this is our value
   add anyway; BM25 search + heatmap + Reflector consume it).
3. **Sink adapter** mapping DataHub metadata-change events → our KB schema.
4. **Dependency isolation** — verifiers flagged that DataHub connector extras can
   conflict in-process; plan per-extra envs or subprocess execution.

### Fit with what we've already shipped
- MetricProof (Feature 6) already reads Snowflake Semantic Views / Databricks Metric
  Views live — DataHub ingestion covers the *cataloged* metadata tier around it.
- Ingested definitions land in the KB → immediately searchable via the BM25 hybrid
  search, visible in the retrieval heatmap, and feed the Reflector roadmap.

## Caveats
License findings checked July 2026 and time-sensitive. Airbyte's embedding permission
is the licensor's FAQ interpretation, not binding license text. DataHub notion/slack
extras' content depth is documented risk, not hands-on tested — a 1-day spike
(ingest a Notion workspace + one Metabase instance into a file sink) is the cheap
next step before committing.
