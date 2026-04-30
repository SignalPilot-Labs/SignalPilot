---
sidebar_position: 2
---

# SignalPilot Cloud

[SignalPilot Cloud](https://app.signalpilot.ai) is a hosted version of the gateway — no Docker, no self-managed infrastructure.

## Get started

1. Sign up at [app.signalpilot.ai](https://app.signalpilot.ai) — free tier available.
2. Create an API key in Settings → API Keys.
3. Add connections in the Connections UI (Snowflake, BigQuery, PostgreSQL, etc.).
4. Point Claude Code at the cloud gateway.

## Connect Claude Code to the cloud

```bash
claude mcp add --transport http signalpilot https://gateway.signalpilot.ai/mcp \
  --header "Authorization: Bearer YOUR_API_KEY"
```

Replace `YOUR_API_KEY` with the key from step 2.

## MCP config for other clients

```json
{
  "mcpServers": {
    "signalpilot": {
      "type": "http",
      "url": "https://gateway.signalpilot.ai/mcp",
      "headers": {
        "Authorization": "Bearer YOUR_API_KEY"
      }
    }
  }
}
```

## What cloud adds over self-host

| Feature | Self-host | Cloud |
|---------|-----------|-------|
| SSO (Clerk) | No | Yes |
| Multi-tenant isolation | Manual | Automatic |
| Managed history & dashboards | No | Yes |
| Encrypted credential storage | Local SQLite | Managed |
| SLA / enterprise support | Community | Available |

## Plugin with cloud

The Claude Code plugin works with the cloud gateway without modification — the skills are local to Claude Code and the MCP tools call the cloud endpoint using your API key.

```bash
claude plugin marketplace add SignalPilot-Labs/signalpilot-plugin
claude plugin install signalpilot-dbt@signalpilot
```
