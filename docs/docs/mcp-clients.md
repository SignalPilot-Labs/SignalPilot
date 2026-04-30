---
sidebar_position: 8
---

# MCP Client Setup

SignalPilot works with any MCP-compatible client that supports **streamable-http** transport.

## Claude Desktop

```json
{
  "mcpServers": {
    "signalpilot": {
      "type": "streamable-http",
      "url": "http://localhost:8081/mcp"
    }
  }
}
```

## Claude Code (CLI)

```bash
claude mcp add signalpilot --transport streamable-http http://localhost:8081/mcp
```

## Cloud mode

For SignalPilot Cloud, use your API key in the header:

```json
{
  "mcpServers": {
    "signalpilot": {
      "type": "streamable-http",
      "url": "https://gateway.signalpilot.ai/mcp",
      "headers": {
        "x-api-key": "sk_your_key_here"
      }
    }
  }
}
```

## Other clients

Any client implementing the [MCP specification](https://spec.modelcontextprotocol.io/) with streamable-http transport will work. The endpoint is:

- **Local**: `http://localhost:8081/mcp`
- **Cloud**: `https://gateway.signalpilot.ai/mcp`
