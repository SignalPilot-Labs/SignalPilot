# Workspaces Agent

This directory contains the agent runtime for SignalPilot Workspaces.

## Contents

- `CLAUDE.md` — the canonical system prompt baked into every Workspaces sandbox container. This is the single source of truth; do not duplicate it.
- `sandbox/` — vendored AutoFyn server, trimmed for Workspaces. See `sandbox/VENDORED.md` for the full change log vs the source.
- `skills_bridge/` — documentation of how SignalPilot skills (`plugin/`) and MCP tools are surfaced inside the sandbox.

## How the Runtime Works

workspaces-api spawns a sandbox container from `sandbox/Dockerfile.gvisor` for each run. The container runs `server.py`, an aiohttp HTTP server that:

1. Validates all requests via `X-Internal-Secret` HMAC (secret minted per-run by workspaces-api).
2. Accepts `POST /session/start` with the user's prompt and run configuration.
3. Starts a Claude Code SDK session (`claude_agent_sdk`) with the baked `CLAUDE.md` as the system prompt.
4. Streams events over `GET /session/{id}/events` (SSE).
5. Accepts follow-up messages, interrupts, and approval unlocks.

Skills from `plugin/` are baked into `/opt/workspaces/.claude/skills/` at image build time. MCP tool configuration (`~/.claude.json` `mcpServers` block) is written by workspaces-api at run start, pointing to the gateway MCP endpoint with a per-run API key.
