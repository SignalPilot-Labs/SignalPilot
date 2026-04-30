---
sidebar_position: 1
---

# Connect Claude Code

Claude Code is the recommended client for SignalPilot. It supports the plugin (skills + verifier agent) and has native `streamable-http` MCP support.

## One-liner

```bash
claude mcp add --transport http signalpilot http://localhost:3300/mcp
```

For SignalPilot Cloud:

```bash
claude mcp add --transport http signalpilot https://gateway.signalpilot.ai/mcp \
  --header "Authorization: Bearer YOUR_API_KEY"
```

## Verify tools loaded

After adding the server, start a Claude Code session and run:

```
/mcp
```

You should see `signalpilot` listed with status `connected` and 32 tools available. Or ask Claude directly:

> "List the MCP tools available from SignalPilot."

Claude should enumerate tools like `query_database`, `list_tables`, `dbt_error_parser`, etc.

## Troubleshoot handshake

**Gateway not reachable**

```bash
curl http://localhost:3300/health
# Should return {"status":"ok"}
```

If this fails, check that the stack is running: `docker compose ps`

**Wrong port**

The gateway runs on `:3300`, not `:8081` (old default). If you have a stale `claude mcp` entry, remove and re-add:

```bash
claude mcp remove signalpilot
claude mcp add --transport http signalpilot http://localhost:3300/mcp
```

**Tools not appearing**

Try restarting Claude Code's MCP connection:

```bash
claude mcp restart signalpilot
```

**Auth error (cloud)**

Verify your API key is set and not expired. Keys are shown once on creation in the Cloud UI — if you've lost it, rotate it in Settings → API Keys.

## Next step

Install the plugin to get skills and the verifier agent:

```bash
claude plugin marketplace add SignalPilot-Labs/signalpilot-plugin
claude plugin install signalpilot-dbt@signalpilot
```

See [Plugin overview](/docs/plugin) for details.
