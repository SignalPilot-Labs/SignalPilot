# SignalPilot MCP — Claude Code Integration

Control your remote SignalPilot gateway from Claude Code on your local machine.

This package provides an MCP (Model Context Protocol) server that runs locally
and proxies all tool calls to your SignalPilot gateway over HTTP. Once installed,
Claude Code can query databases, manage connections, launch sandboxes, and view
audit logs — all through natural conversation.

## Quick Start

### 1. Install the package

```bash
# From the repo
cd signalpilot/claude-code-mcp
pip install -e .

# Or run directly with python
python -m signalpilot_mcp
```

### 2. Configure Claude Code

**Option A — Global** (all projects get SignalPilot tools):

Add to `~/.claude/settings.json`:

```json
{
  "mcpServers": {
    "signalpilot": {
      "command": "signalpilot-mcp-remote",
      "env": {
        "SIGNALPILOT_URL": "http://YOUR_SERVER:3300",
        "SIGNALPILOT_API_KEY": "your-api-key-if-set"
      }
    }
  }
}
```

**Option B — Per-project** (only this project gets SignalPilot tools):

Add to `PROJECT_DIR/.claude/settings.json`:

```json
{
  "mcpServers": {
    "signalpilot": {
      "command": "signalpilot-mcp-remote",
      "env": {
        "SIGNALPILOT_URL": "http://YOUR_SERVER:3300"
      }
    }
  }
}
```

**Option C — python -m fallback** (if the script isn't in PATH):

```json
{
  "mcpServers": {
    "signalpilot": {
      "command": "python",
      "args": ["-m", "signalpilot_mcp"],
      "env": {
        "SIGNALPILOT_URL": "http://YOUR_SERVER:3300"
      }
    }
  }
}
```

**Option D — One-line setup script:**

```bash
./signalpilot/claude-code-mcp/setup-claude-code.sh http://YOUR_SERVER:3300
# Installs the package and prints the config to paste into settings.json
```

### 3. Use it

Open Claude Code and start talking:

```
> "Show me what databases are connected to SignalPilot"
> "Query the enterprise-pg connection: SELECT count(*) FROM orders WHERE created_at > '2024-01-01'"
> "What's the schema for the users table on warehouse-pg?"
> "Show me the last 10 audit log entries"
> "Check the connection health for enterprise-pg"
> "What's the current query budget status?"
```

## Available Tools

| Tool | Description |
|------|-------------|
| `signalpilot_health` | Check gateway status and connectivity |
| `query_database` | Run governed read-only SQL (with full governance pipeline) |
| `list_connections` | List all configured database connections |
| `add_connection` | Register a new database connection |
| `remove_connection` | Remove a database connection |
| `test_connection` | Test connectivity to a database |
| `describe_schema` | Get full table/column schema for a connection |
| `connection_health` | View latency percentiles and error rates |
| `list_sandboxes` | List active Firecracker microVM sandboxes |
| `create_sandbox` | Launch a new isolated sandbox |
| `destroy_sandbox` | Terminate a sandbox |
| `execute_code` | Run Python code in a sandbox |
| `audit_log` | View the query/execution audit trail |
| `check_budget` | Check query cost budget status |
| `cache_stats` | View query cache hit rates |
| `get_settings` | View gateway configuration |
| `update_settings` | Modify gateway settings |

## Configuration

| Environment Variable | Default | Description |
|---------------------|---------|-------------|
| `SIGNALPILOT_URL` | `http://localhost:3300` | Gateway base URL |
| `SIGNALPILOT_API_KEY` | (none) | API key for authenticated gateways |

## Network Requirements

Your local machine must be able to reach the SignalPilot gateway over HTTP.
Common setups:

- **Same machine**: `http://localhost:3300` (default)
- **Docker on same machine**: `http://host.docker.internal:3300`
- **Remote server**: `http://your-server.example.com:3300`
- **SSH tunnel**: `ssh -L 3300:localhost:3300 your-server` then use `http://localhost:3300`
- **Tailscale/WireGuard**: Use your Tailscale hostname or WireGuard IP

## Governance

All queries through this MCP server go through the full SignalPilot governance
pipeline on the gateway side:

- SQL validation (DDL/DML blocked, statement stacking blocked)
- Automatic LIMIT injection/clamping
- PII detection and redaction
- Query cost estimation and budget tracking
- Full audit trail logging

You get the same safety guarantees whether using the web UI, the local MCP
server, or this remote MCP server.
