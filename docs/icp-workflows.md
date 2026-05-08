# SignalPilot — ICP Workflows & Surface Map

Five personas, five different relationships with data. The core insight: **technical users don't need our notebook** — they need governed data access inside *their* tools. The custom web notebook exists for non-technical users who need zero-setup, AI-assisted data exploration.

---

## 1. Persona → Surface → Platform

Every persona reaches SignalPilot's governed data layer, but through different surfaces. The Gateway API is the single chokepoint — every query, every tool, every notebook cell passes through it. This is where auth, permissions, and audit happen. No surface bypasses governance.

- **Engineers and Scientists** use their own tools (VS Code, Cursor, CLI). They install the `signalpilot-sp` SDK or connect via MCP. They don't need our UI.
- **Analysts** live in the web notebook. They write SQL against governed connections with schema autocomplete. The cloud kernel runs their code.
- **PMs** also use the web notebook, but lean on the AI cell — describe what they want, AI generates the query.
- **Executives** never touch a notebook. They consume published reports — read-only, live-updating links.

```mermaid
graph LR
    subgraph Personas
        ENG["🔧 Data Engineer"]
        SCI["🔬 Data Scientist"]
        ANA["📊 Data Analyst"]
        PM["📋 Product Manager"]
        EXEC["👔 Executive"]
    end

    subgraph Surfaces["User Surfaces"]
        IDE["Local IDE<br/>(VS Code / Cursor)"]
        MCP["AI Tools<br/>(Claude / Cursor MCP)"]
        CLI["CLI / CI-CD"]
        WEB_NB["✨ Web Notebook<br/>(Custom — 4 cell types)"]
        PUB["Published Reports<br/>(Read-only links)"]
    end

    subgraph SignalPilot["SignalPilot Platform"]
        SDK["signalpilot-sp SDK<br/>(pip install)"]
        MCPS["Governed MCPs<br/>(query, schema, dbt)"]
        GW["Gateway API<br/>(Auth + Governance)"]
        KERNEL["Cloud Kernel<br/>(ipykernel sandbox)"]
        AI["AI Layer<br/>(query gen, autocomplete)"]
    end

    subgraph Data["Governed Data Layer"]
        CONN["Connections<br/>(Postgres, BQ, Snowflake...)"]
        SCHEMA["Schema Catalog"]
        DBT["dbt Models"]
    end

    ENG --> IDE
    ENG --> CLI
    ENG --> MCP
    SCI --> IDE
    SCI --> MCP
    SCI --> WEB_NB
    ANA --> WEB_NB
    ANA --> MCP
    PM --> WEB_NB
    EXEC --> PUB

    IDE --> SDK
    CLI --> SDK
    MCP --> MCPS
    WEB_NB --> KERNEL
    WEB_NB --> AI
    PUB --> GW

    SDK --> GW
    MCPS --> GW
    KERNEL --> GW
    AI --> GW

    GW --> CONN
    GW --> SCHEMA
    GW --> DBT
```

## 2. Code Comfort vs. SignalPilot Surface

Two axes define which surface each persona gravitates toward:

- **Code comfort** (x-axis): Can they write SQL? Python? Or do they need natural language?
- **Setup tolerance** (y-axis): Will they install packages and configure environments, or do they expect it to "just work" in a browser?

The quadrants map directly to product decisions:
- **Top-right** (high code, full control): Engineers and scientists. Serve them with the SDK and MCP — don't force them into our UI.
- **Bottom-left** (low code, zero setup): PMs and executives. This is where the custom web notebook with AI assistance matters most. If we nail this quadrant, we unlock a market that traditional BI tools serve poorly.
- **Middle**: Analysts straddle the line. They can write SQL but don't want environment management. The web notebook with governed connections and schema autocomplete is their sweet spot.

```mermaid
quadrantChart
    title Persona Placement
    x-axis Low Code Comfort --> High Code Comfort
    y-axis Wants Zero Setup --> Wants Full Control
    quadrant-1 Local IDE and SDK
    quadrant-2 Web Notebook and AI
    quadrant-3 Custom Web Notebook
    quadrant-4 MCP in AI Tools
    Data Engineer: [0.9, 0.85]
    Data Scientist: [0.8, 0.7]
    Data Analyst: [0.45, 0.3]
    Product Manager: [0.15, 0.2]
    Executive: [0.05, 0.15]
```

## 3. The Custom Web Notebook — Cell Types

This is NOT a Jupyter clone. It's a purpose-built notebook with 5 cell types designed for analysts and PMs who need to explore governed data without managing Python environments.

**SQL Cell** — The workhorse. A connection picker dropdown (only shows connections the user has access to), schema-aware autocomplete, and a run button. Output is always a table. This is what analysts use 80% of the time.

**AI Cell** — The unlock for non-technical users. Type a question in English ("show me weekly signups by plan for the last quarter"), the AI generates SQL or Python using the schema catalog, the user reviews and runs. This is what makes SignalPilot accessible to PMs.

**Viz Cell** — No-code charting. Takes the output from a SQL or AI cell above, lets the user pick chart type, columns, colors. Think "Google Sheets chart wizard" not "matplotlib." Powered by a client-side chart library (Observable Plot or Vega-Lite).

**Text Cell** — Markdown for narrative. Analysts use this to annotate their findings, add context, tell the story around the data. Can reference metrics from cells above.

**Python Cell** — Escape hatch for power users. Full pandas/scipy/custom logic via the cloud kernel. Most analysts never touch this; data scientists use it when they need something SQL can't do.

The flow between cells is top-down: SQL/AI cells produce data, Viz cells render it, Text cells narrate it. The notebook then publishes, schedules, or shares — reaching executives who never open a notebook themselves.

```mermaid
graph TD
    subgraph nb["SignalPilot Web Notebook"]
        direction TB

        SQL_CELL["<b>SQL Cell</b><br/>Connection picker dropdown<br/>Schema autocomplete<br/>Run → table output"]
        AI_CELL["<b>AI Cell</b><br/>Natural language input<br/>AI generates SQL or Python<br/>User reviews → runs"]
        VIZ_CELL["<b>Viz Cell</b><br/>No-code chart config<br/>Pick columns, chart type<br/>Auto-renders from data above"]
        TEXT_CELL["<b>Text Cell</b><br/>Markdown narrative<br/>Inline metric references<br/>For storytelling"]
        PY_CELL["<b>Python Cell</b><br/>(Power users only)<br/>pandas, scipy, custom logic<br/>Falls back to full kernel"]

        SQL_CELL --> VIZ_CELL
        AI_CELL --> VIZ_CELL
        SQL_CELL --> TEXT_CELL
        VIZ_CELL --> TEXT_CELL
        PY_CELL --> VIZ_CELL
    end

    PUBLISH["📤 Publish"]
    SCHEDULE["⏰ Schedule"]
    SHARE["🔗 Share Link"]

    nb --> PUBLISH
    nb --> SCHEDULE
    nb --> SHARE

    PUBLISH --> EXEC_VIEW["Executive View<br/>(read-only, live data)"]
    SCHEDULE --> SLACK["Slack / Email<br/>(periodic snapshots)"]
    SHARE --> COLLAB["Team Collaboration<br/>(comment, fork)"]
```

## 4. Workflow Journeys

Five concrete workflows — one per persona. Each shows the end-to-end journey from intent to outcome. The satisfaction scores (1-5) flag where friction exists today.

### Data Analyst — Weekly Metrics Report

The bread-and-butter use case. An analyst who already knows what they want to measure opens their existing notebook, runs governed SQL, adds a chart, publishes for the team. Zero environment setup. The connection picker and schema autocomplete are the key UX — they should never have to ask an engineer "what's the table name?"

```mermaid
journey
    title Data Analyst - Weekly Metrics Report
    section Open
        Go to SignalPilot app: 5: Analyst
        Open existing notebook: 5: Analyst
    section Query
        Pick connection from dropdown: 5: Analyst
        Write SQL with autocomplete: 4: Analyst
        Run query and see table: 5: Analyst
    section Visualize
        Add viz cell: 5: Analyst
        Pick bar chart and columns: 5: Analyst
        Tweak colors and title: 4: Analyst
    section Share
        Add text summary: 4: Analyst
        Click publish: 5: Analyst
        Send link to team: 5: Analyst
```

### Product Manager — Ad-hoc Question

The highest-value, hardest-to-nail workflow. A PM has a business question ("how many users signed up last week by plan?") but can't write the SQL. They describe it in an AI cell, the AI generates a query using the schema catalog, and the PM reviews it. The trust gap at the "reviews generated query" step (scored 3) is the critical UX challenge — the PM can't verify the SQL is correct. Solutions: show a plain-English summary of what the query does, show row count expectations, let them compare against known benchmarks.

```mermaid
journey
    title Product Manager - Ad-hoc Question
    section Ask
        Open SignalPilot: 5: PM
        Create new notebook: 5: PM
        Describe question in AI cell: 5: PM
    section Generate
        AI writes SQL from schema: 5: AI
        PM reviews generated query: 3: PM
        PM clicks Run: 5: PM
    section Result
        Table appears with results: 5: PM
        Auto-suggested chart appears: 5: PM
        Share link in Slack: 5: PM
```

### Data Engineer — Build Governed Connection

The engineer is the enabler. They don't consume data through SignalPilot's web notebook — they *build the governed layer* that everyone else consumes. Their workflow happens in their own IDE with the sp SDK. The payoff is in the "Enable" section: once they've set up a governed connection and dbt models, every analyst and PM in the org can instantly query that data through the web notebook or MCP. The engineer's work multiplies across the whole team.

```mermaid
journey
    title Data Engineer - Build Governed Connection
    section Setup
        Open VS Code locally: 5: Engineer
        Install signalpilot-sp: 5: Engineer
        Configure API key: 4: Engineer
    section Build
        Create connection in admin: 5: Engineer
        Define allowed schemas: 5: Engineer
        Write dbt models: 4: Engineer
    section Test
        Run sp.query in notebook: 5: Engineer
        Verify governance rules: 5: Engineer
        Push dbt models to CI: 4: Engineer
    section Enable
        Analysts query via web: 5: Analyst
        PMs ask AI about data: 5: PM
```

### Data Scientist — Churn Analysis

Scientists need the most flexibility. They pull governed data via sp SDK, but then join it with local files (CSVs, survey exports), run statistical models, and iterate fast. This workflow is deliberately local — the cloud kernel adds latency and can't access local files. The scientist only touches the web notebook at the end, to publish findings for non-technical stakeholders. SignalPilot's value here is governed data access + a publishing layer, not the notebook itself.

```mermaid
journey
    title Data Scientist - Churn Analysis
    section Explore
        Open VS Code with Jupyter: 5: Scientist
        Pull cohort data via sp: 5: Scientist
        Join with local CSV: 5: Scientist
    section Analyze
        Statistical tests in pandas: 5: Scientist
        Build visualizations: 5: Scientist
        Train logistic regression: 4: Scientist
    section Share
        Push findings to web notebook: 4: Scientist
        Add viz cells for stakeholders: 4: Scientist
        Publish for review: 5: Scientist
```

### MCP Native — AI-first Data Access

The emerging workflow that bypasses notebooks entirely. A user opens Claude or Cursor, asks a data question, and the AI calls SignalPilot's governed MCP tools behind the scenes. The gateway checks permissions, runs the query, and results come back inline in the conversation. No notebook, no setup, no SQL. This is arguably the lowest-friction surface SignalPilot offers and it's already built. Every persona can use this — from engineers debugging in Cursor to PMs asking Claude a question.

```mermaid
journey
    title MCP Native - AI-first Data Access
    section Ask
        Open Claude or Cursor: 5: User
        Ask data question naturally: 5: User
    section Execute
        AI calls governed MCP tool: 5: AI
        Gateway checks permissions: 5: Gateway
        Query runs on connection: 5: Gateway
    section Answer
        Results return inline: 5: User
        Ask follow-up question: 5: User
        No notebook needed: 5: User
```

## 5. What We Build vs. What Exists

The build/reuse/done split shows why this is feasible with a small team.

**Already done** — The Gateway API, auth (Clerk + API keys), the WebSocket kernel protocol, and rich output (HTML tables, PNG charts, full MIME bundles) are shipped. This is the hard infrastructure layer.

**Reuse from OSS** — Monaco editor (same editor engine as VS Code) for SQL and Python cells. ipykernel for cloud code execution. MCP protocol for AI tool access. A chart library (Observable Plot or Vega-Lite) for no-code visualizations. The sp SDK for local data access.

**We build** — Four things: (1) the custom web notebook with its 5 cell types, (2) the governance UX layer (connection picker, schema browser, permission management), (3) AI query generation that's schema-aware and respects governance rules, (4) publish/schedule system so notebooks become living reports.

The custom notebook is the biggest build, but it's a frontend on top of infrastructure that already exists. The kernel protocol, rich output, auth — all done. We're building the UI shell, not the engine.

```mermaid
graph TB
    subgraph build["🔨 We Build"]
        CUSTOM_NB["Custom Web Notebook<br/>(4 cell types + AI)"]
        GOV["Governance Layer<br/>(connections, permissions, audit)"]
        AI_LAYER["AI Query Generation<br/>(schema-aware, governed)"]
        PUBLISH_SYS["Publish / Schedule System"]
    end

    subgraph reuse["♻️ We Reuse"]
        MONACO["Monaco Editor<br/>(SQL + Python cells)"]
        KERNEL_SYS["ipykernel<br/>(cloud execution)"]
        SP_SDK["signalpilot-sp SDK<br/>(local access)"]
        MCP_PROTO["MCP Protocol<br/>(AI tool access)"]
        CHART_LIB["Chart Library<br/>(Observable Plot / Vega-Lite)"]
    end

    subgraph exists["✅ Already Done"]
        GW_API["Gateway API"]
        AUTH["Auth (Clerk + API keys)"]
        WS["WebSocket Kernel Protocol"]
        RICH["Rich Output (HTML, PNG, MIME)"]
    end

    CUSTOM_NB --> MONACO
    CUSTOM_NB --> KERNEL_SYS
    CUSTOM_NB --> CHART_LIB
    CUSTOM_NB --> AI_LAYER
    AI_LAYER --> GOV
    GOV --> GW_API
    KERNEL_SYS --> WS
    WS --> RICH
```
