# Direction — The SOTA Slack Data Analyst Agent

**This is the north star, not the backlog.** The backlog is [README.md](README.md) — small tasks, shipped weekly. This file is where we want to be, so every small task can be checked against it: does this move us toward the SOTA Slack agent, and does it help sell?

## Where we want to be

**SP is the data analyst on your team who happens to live in Slack.** You talk to it like a colleague: it remembers how your company defines things, it knows what you personally care about, it shows up with the numbers before you ask, and anyone in the workspace can pull it into any conversation to settle a question with data. Underneath, it is the same governed, benchmark-leading engine (#1 Spider 2.0-DBT) — Slack is the body, the data agent is the brain.

The reference experience bar is Anthropic's Claude in Slack (Claude Tag) for conversation quality — plus everything a *data analyst* teammate does that a general assistant doesn't: memory of the business, proactive reporting, and receipts for every number.

## The pillars

### 1. Conversational parity — "talks like a teammate"
Follow-ups with context, steer/question a running analysis, stop on request, no pipeline for small talk. The front door is an **orchestrator agent with the gateway MCP**: anything reachable via the 40 MCP tools (connections, schemas, knowledge base, query history) is answered in seconds without spinning a notebook — the full analysis engine is reserved for real data work. **Status: in flight — Task 1.** This is the foundation; nothing else lands if the basic conversation feels like a vending machine.

### 2. Company memory — "knows our business" *(moat)*
SP learns each company's semantics: metric definitions, table caveats, "revenue = `fct_revenue`, exclude test orgs," fiscal calendar quirks. Every correction in Slack compounds into permanently better answers *for that company*.
- **Foundation exists:** org/project-scoped knowledge base with MCP tools (`get/search/propose/archive_knowledge`, `gateway/mcp/tools/knowledge.py`) — the agent can already read and write it mid-analysis.
- **Missing:** automatic capture from conversations (user corrects SP → SP proposes a knowledge doc), review/approval flow so memory stays trustworthy, and surfacing ("I'm using your definition of ARR from May").
- **Sales unlock:** the killer demo ("it knows OUR definitions") and the switching cost — after three months, SP knows things no competitor can replicate on day one.

### 3. Personal & channel memory — "knows *you*"
Per-user: role, preferred grain, timezone, the metrics they always ask about. Per-channel: #growth defaults to growth metrics, #finance to the finance schema, channel-level default project/branch (partially exists: `channel_defaults` in the Slack worker).
- **Sales unlock:** the CFO's second question is faster than the first — retention through personalization.

### 4. Proactiveness — "shows up before you ask" *(biggest sales lever)*
- **Scheduled digests:** "every Monday 9am, post revenue summary to #leadership." Natural language → schedule.
- **Subscriptions:** "keep me posted on this metric weekly" as a follow-up to any analysis.
- **Anomaly alerts:** watch key metrics, post when something breaks trend — with the driver analysis already attached.
- **Missing everything:** no scheduler exists in the codebase today. Needs: schedule store, cron runner, and the delivery path (which we already have).
- **Sales unlock:** a digest in #leadership puts SP in front of every exec weekly without prompting — one champion becomes org-wide visibility. It is also the demo close ("want this every Monday?") and the retention anchor (alerts you rely on don't get churned).

### 5. Native Slack agent surface — "first-class citizen"
Adopt Slack's agent platform (Agentic API / AI apps): assistant side panel, suggested prompts, status updates ("querying Snowflake…"), thread-context APIs — instead of only mrkdwn messages. Marketplace listing in the **AI agents category**.
- **Sales unlock:** distribution. Marketplace is Fahim's #1 growth question; the agents category is new and thin — early listings get outsized visibility.

### 6. Shareable receipts — "numbers you can trust and pass on"
Every answer keeps its trail (notebook, SQL, confidence — exists today). Next: results shareable with people *outside* SignalPilot accounts, dashboards that stay live, exports where the audience is (Slack canvas, link).
- **Sales unlock:** every shared artifact is a lead in another team or company. Trust receipts also arm champions against "did the AI make this up?"

### 7. Enterprise trust pack — "passes security review"
Governed SQL, audit log, encrypted credentials (exist) + org-level key (Task 2), SSO, RBAC on who can query what, data-residency answers.
- **Sales unlock:** doesn't excite users; *unblocks deals*. Our governance story is genuinely differentiated — competitors demo faster, we pass procurement.

## The compounding loop we're building

Conversation (1) generates corrections → memory (2,3) makes answers better → better answers earn schedules and alerts (4) → proactive posts reach people who never installed anything (5,6) → some of them are buyers (7 closes them). Each pillar feeds the next; that's why the order above is roughly the build order.

## Explicitly not the direction

- Notion as a primary surface (revisit only with distribution evidence)
- Being a BI tool (dashboards are outputs, not the product — the analyst is the product)
- Chat-with-your-data toys without governance (that market is crowded and untrusted)
- More chart types / warehouse connectors / notebook UI polish as growth bets — they deepen existing users, they don't create new ones

## How to use this file

When picking the next task for README.md, ask: which pillar does it advance, and does it have a user win this week? If a proposed task advances no pillar, it's probably maintenance — fine, but don't confuse it with progress toward SOTA.
