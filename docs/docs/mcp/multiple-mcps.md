---
sidebar_position: 3
---

# Running Multiple MCP Servers

Claude Code and other MCP clients support multiple servers simultaneously. SignalPilot works alongside other MCP servers — filesystem, GitHub, browser, etc.

## Example `.mcp.json`

A project using SignalPilot + a filesystem MCP + a GitHub MCP:

```json
{
  "mcpServers": {
    "signalpilot": {
      "type": "http",
      "url": "http://localhost:3300/mcp"
    },
    "filesystem": {
      "type": "stdio",
      "command": "npx",
      "args": ["-y", "@modelcontextprotocol/server-filesystem", "/path/to/project"]
    },
    "github": {
      "type": "stdio",
      "command": "npx",
      "args": ["-y", "@modelcontextprotocol/server-github"],
      "env": {
        "GITHUB_PERSONAL_ACCESS_TOKEN": "ghp_your_token"
      }
    }
  }
}
```

For Claude Code, you can also add servers individually and they combine:

```bash
claude mcp add --transport http signalpilot http://localhost:3300/mcp
claude mcp add --transport stdio filesystem npx -y @modelcontextprotocol/server-filesystem /path/to/project
```

## Tool namespace conflicts

Each MCP server declares its tools independently. If two servers expose a tool with the same name (e.g. `query_database`), Claude Code uses the server name as a prefix to disambiguate. SignalPilot's tools are prefixed `signalpilot__` internally in multi-server contexts.

To avoid confusion, SignalPilot tool names are intentionally specific (`query_database`, `list_tables`, `dbt_error_parser`) and unlikely to conflict with general-purpose MCP servers.

## Tool ordering

Claude Code presents all available tools to the model. The model chooses which tool to call based on the task. If you want to steer Claude toward SignalPilot tools for data tasks, mention it in your `CLAUDE.md`:

```
For any database or dbt task, use the SignalPilot MCP tools (signalpilot server).
Always call list_database_connections before querying to confirm the right connection is active.
```

See [CLAUDE.md recipes](/docs/workflows/claude-md-recipes) for more templates.

## Disabling individual tools

If a specific SignalPilot tool conflicts or you want to limit Claude's surface area, you can disable individual tools in Claude Code's MCP settings. This does not affect other tools from the same server.

## Connection health across servers

Use `connection_health` from SignalPilot to verify database connectivity independently of whether the other MCP servers are working. Each server's health is independent.
