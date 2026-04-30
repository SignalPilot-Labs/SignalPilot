---
sidebar_position: 1
---

# Install the Plugin

## Prerequisites

- Claude Code installed and working
- SignalPilot MCP server added (see [Connect Claude Code](/docs/mcp/connect-claude-code))

## Install

```bash
claude plugin marketplace add SignalPilot-Labs/signalpilot-plugin
claude plugin install signalpilot-dbt@signalpilot
```

The first command registers the plugin marketplace source. The second installs the `signalpilot-dbt` skill set from the SignalPilot plugin.

## Verify skills loaded

Start a Claude Code session and run:

```
/skills
```

You should see the SignalPilot skills listed:

- `dbt-workflow`
- `dbt-write`
- `dbt-debugging`
- `dbt-date-spines`
- `sql-workflow`
- `duckdb-sql`
- `snowflake-sql`
- `bigquery-sql`
- `sqlite-sql`

Or ask Claude: "What SignalPilot skills are available?"

## Test the install

In a project with a dbt project, ask:

> "Build the `orders` dbt model."

Claude should automatically load the `dbt-workflow` skill and follow the 5-step lifecycle (plan → scan → govern → build → verify) without you specifying how.

## Update

```bash
claude plugin update signalpilot-dbt@signalpilot
```

Updates pull the latest skill definitions from the plugin repository. No MCP server restart needed.

## Uninstall

```bash
claude plugin uninstall signalpilot-dbt@signalpilot
claude plugin marketplace remove SignalPilot-Labs/signalpilot-plugin
```
