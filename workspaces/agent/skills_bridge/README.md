# Skills Bridge

Documents how SignalPilot skills and MCP tools are surfaced inside the Workspaces sandbox. Round 1 is documentation only; implementation happens in Round 7.

## SignalPilot Skills

The canonical skills home in this repository is `plugin/`. At container build time, the Dockerfile copies `plugin/` into `/opt/workspaces/.claude/skills/` inside the sandbox image:

```dockerfile
COPY --chown=agentuser:agentuser ./plugin/ /opt/workspaces/.claude/skills/
```

The Claude Code SDK discovers skills via `add_dirs` pointing to `/opt/workspaces/.claude/skills/`. If `plugin/` is empty at build time, no skills are available; the agent falls back to tool-only operation (documented in `CLAUDE.md §4`).

## SignalPilot MCP Tools

The SignalPilot gateway exposes MCP tools over `streamable-http` transport (`SP_MCP_TRANSPORT=streamable-http`). The gateway MCP server authenticates connections via MCP API keys.

At run start, workspaces-api writes `~/.claude.json` inside the sandbox with an `mcpServers` block pointing to the gateway MCP endpoint and carrying a per-run API key:

```json
{
  "mcpServers": {
    "signalpilot": {
      "type": "http",
      "url": "<SP_GATEWAY_URL>/mcp",
      "headers": {
        "Authorization": "Bearer <per_run_mcp_key>"
      }
    }
  }
}
```

The per-run MCP key is minted by workspaces-api, scoped to the user's connectors, and expires when the run ends. The agent calls `list_tools` to discover available tools at session start — no tool names are hardcoded.

## Credential Flow

The agent never receives database credentials. All SQL execution goes through the MCP `query` tool family — the gateway decrypts credentials in its own process, executes the query, and returns results. For dbt runs, workspaces-api writes a `~/.dbt/profiles.yml` pointing to the dbt-proxy at `host.containers.internal:<port>`; the proxy authenticates via run-scoped token (see `ARCHITECTURE.md §3`).
