---
sidebar_position: 2
---

# Connect Other MCP Clients

:::caution Experimental
The 32 MCP tools work over `streamable-http` from any MCP client (Cursor, Codex, custom Agent SDK) — but the **SignalPilot skills are Claude Code-specific** and don't run outside it. You'll have the tools without skill orchestration. The Claude Code plugin is the supported path; treat the configs below as best-effort.
:::

## Claude Desktop

Add to `~/Library/Application Support/Claude/claude_desktop_config.json` (macOS) or `%APPDATA%\Claude\claude_desktop_config.json` (Windows):

```json
{
  "mcpServers": {
    "signalpilot": {
      "type": "http",
      "url": "http://localhost:3300/mcp"
    }
  }
}
```

For cloud with bearer auth:

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

## Cursor

Add to `.cursor/mcp.json` in your project root:

```json
{
  "mcpServers": {
    "signalpilot": {
      "type": "http",
      "url": "http://localhost:3300/mcp"
    }
  }
}
```

## Codex / OpenAI Agent SDK

```json
{
  "mcpServers": {
    "signalpilot": {
      "type": "http",
      "url": "http://localhost:3300/mcp"
    }
  }
}
```

## Custom Agent SDK

Any client implementing [MCP streamable-http transport](https://spec.modelcontextprotocol.io/) can connect:

- **Local endpoint**: `http://localhost:3300/mcp`
- **Cloud endpoint**: `https://gateway.signalpilot.ai/mcp`
- **Auth header**: `Authorization: Bearer YOUR_API_KEY`

The gateway returns standard MCP responses. All 32 tools are callable — governance runs on the server side regardless of which client you use.

## Bearer token auth

When API keys are configured, pass them as a bearer token:

```
Authorization: Bearer sk_your_key_here
```

For local self-hosted deployments without API key enforcement, no auth header is required.

## Limitations for non-Claude clients

- **No skills** — dbt-workflow, sql-workflow, and dialect-specific skills are Claude Code-specific. You'll need to craft your own prompt instructions.
- **No verifier agent** — the post-build 7-check protocol is a Claude Code plugin agent. It won't run.
- **No auto-skill loading** — you must manually structure your prompts to call the right tools in the right order.

For full functionality, use [Claude Code](/docs/mcp/connect-claude-code).
