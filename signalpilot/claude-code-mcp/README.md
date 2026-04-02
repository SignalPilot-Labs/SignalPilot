# SignalPilot MCP — Claude Code Integration

Control your remote SignalPilot gateway and self-improving agent from Claude Code
on your local machine.

This package provides an MCP (Model Context Protocol) server that runs locally
and proxies all tool calls to your SignalPilot gateway and self-improve monitor
over HTTP. Once installed, Claude Code can query databases, manage connections,
and — most importantly — start, monitor, pause, steer, and stop the autonomous
self-improving AI agent, all through natural conversation.

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

Add to `~/.claude/settings.json` (global) or `PROJECT_DIR/.claude/settings.json` (per-project):

```json
{
  "mcpServers": {
    "signalpilot": {
      "command": "signalpilot-mcp-remote",
      "env": {
        "SIGNALPILOT_URL": "http://YOUR_SERVER:3300",
        "SIGNALPILOT_MONITOR_URL": "http://YOUR_SERVER:3401",
        "SIGNALPILOT_API_KEY": ""
      }
    }
  }
}
```

If `signalpilot-mcp-remote` isn't in your PATH, use `python -m`:

```json
{
  "mcpServers": {
    "signalpilot": {
      "command": "python",
      "args": ["-m", "signalpilot_mcp"],
      "env": {
        "SIGNALPILOT_URL": "http://YOUR_SERVER:3300",
        "SIGNALPILOT_MONITOR_URL": "http://YOUR_SERVER:3401"
      }
    }
  }
}
```

Or use the setup script:

```bash
./signalpilot/claude-code-mcp/setup-claude-code.sh http://YOUR_SERVER:3300
```

### 3. Use it

Open Claude Code and start talking:

**Self-improving agent:**
```
> "Start an improvement run focused on test coverage for 30 minutes"
> "What improvement runs have been done recently?"
> "Show me the output from the latest run"
> "Pause the current run"
> "Tell the agent to focus on security instead"
> "Resume the run"
> "What files did run abc-123 change?"
> "Stop the current improvement run"
```

**Database queries:**
```
> "Show me what databases are connected to SignalPilot"
> "Query enterprise-pg: SELECT count(*) FROM orders WHERE created_at > '2024-01-01'"
> "What's the schema for the users table?"
> "Check the connection health for enterprise-pg"
```

## Available Tools (36)

### Self-Improve Agent (15 tools)

| Tool | Description |
|------|-------------|
| `agent_health` | Check if the agent is idle or running, with timing info |
| `start_improvement_run` | Start a new autonomous improvement run with a custom prompt |
| `resume_improvement_run` | Resume a stopped or rate-limited run |
| `stop_improvement_run` | Gracefully stop — agent commits work and creates PR |
| `kill_improvement_run` | Immediately kill — no cleanup, no PR |
| `list_improvement_runs` | List recent runs with status, cost, and PR links |
| `get_improvement_run` | Detailed info for a specific run |
| `get_run_tool_calls` | See what tools the agent used (file reads, edits, commands) |
| `get_run_output` | View the agent's LLM output and key events |
| `get_run_diff` | See what files the agent changed (+/- lines) |
| `pause_improvement_run` | Pause a running agent |
| `resume_improvement_signal` | Resume a paused agent |
| `inject_agent_prompt` | Send a message to redirect the agent mid-run |
| `unlock_improvement_run` | Let the agent end early (before time lock expires) |
| `list_agent_branches` | List available git branches |

### Gateway & Database (21 tools)

| Tool | Description |
|------|-------------|
| `signalpilot_health` | Check gateway status and connectivity |
| `get_settings` / `update_settings` | View/modify gateway configuration |
| `query_database` | Run governed read-only SQL (full governance pipeline) |
| `list_connections` | List all configured database connections |
| `add_connection` / `add_connection_uri` | Register a new database connection |
| `remove_connection` | Remove a connection |
| `test_connection` | Test connectivity |
| `describe_schema` | Get full table/column schema |
| `connection_health` | View latency percentiles and error rates |
| `list_sandboxes` / `create_sandbox` / `destroy_sandbox` | Manage Firecracker sandboxes |
| `execute_code` | Run Python code in an isolated sandbox |
| `get_annotations` | View schema annotations, PII flags, sensitivity |
| `detect_pii` | Auto-detect PII columns in a database |
| `audit_log` | View the query/execution audit trail |
| `check_budget` | Check query cost budget status |
| `cache_stats` / `invalidate_cache` | View and manage the query cache |

## Configuration

| Environment Variable | Default | Description |
|---------------------|---------|-------------|
| `SIGNALPILOT_URL` | `http://localhost:3300` | Gateway base URL |
| `SIGNALPILOT_MONITOR_URL` | `http://localhost:3401` | Self-improve monitor URL |
| `SIGNALPILOT_API_KEY` | (none) | API key for authenticated gateways |

## Connecting to a Remote Server

Your local machine must be able to reach both the gateway (port 3300) and
the self-improve monitor (port 3401) over HTTP. Choose the setup that
matches your deployment:

### Same machine (local Docker)

No network config needed — everything is on localhost:

```
SIGNALPILOT_URL=http://localhost:3300
SIGNALPILOT_MONITOR_URL=http://localhost:3401
```

### SSH tunnel (recommended for remote servers)

The most secure option — no firewall changes needed. Run this on your
local machine before opening Claude Code:

```bash
ssh -L 3300:localhost:3300 -L 3401:localhost:3401 your-server
```

Then use `http://localhost:3300` and `http://localhost:3401` in your config.
The tunnel forwards traffic over your existing SSH connection. Add `-N` to
run in the background without opening a shell:

```bash
ssh -N -L 3300:localhost:3300 -L 3401:localhost:3401 your-server &
```

### Tailscale / WireGuard

If both machines are on the same Tailscale or WireGuard network, use the
VPN IP or hostname directly — no tunnels or port changes needed:

```
SIGNALPILOT_URL=http://your-tailscale-hostname:3300
SIGNALPILOT_MONITOR_URL=http://your-tailscale-hostname:3401
```

### Direct exposure (LAN / cloud VM)

The Docker Compose files already bind ports to all interfaces (`0.0.0.0`),
so if your server's firewall allows it, you can connect directly:

```
SIGNALPILOT_URL=http://your-server-ip:3300
SIGNALPILOT_MONITOR_URL=http://your-server-ip:3401
```

**Verify ports are exposed** — check `docker-compose.dev.yml` and
`self-improve/docker-compose.yml` for port bindings like `"3300:3300"`.
The short form (`"3300:3300"`) binds to all interfaces. If you see
`"127.0.0.1:3300:3300"`, it's localhost-only — change it to `"3300:3300"`
to allow remote connections.

**Security note:** Exposing ports directly means anyone who can reach your
server can access SignalPilot. Set an API key (`SP_API_KEY` env var on the
gateway) and use `SIGNALPILOT_API_KEY` in your Claude Code config, or use
an SSH tunnel instead.

### Verifying connectivity

After configuring, run the built-in check:

```bash
SIGNALPILOT_URL=http://... SIGNALPILOT_MONITOR_URL=http://... signalpilot-mcp-remote --check
```

## Governance

All queries through this MCP server go through the full SignalPilot governance
pipeline on the gateway side:

- SQL validation (DDL/DML blocked, statement stacking blocked)
- Automatic LIMIT injection/clamping
- PII detection and redaction
- Query cost estimation and budget tracking
- Full audit trail logging
