---
sidebar_position: 2
---

# Getting Started

Get SignalPilot running locally in under 5 minutes.

## Prerequisites

- Docker Desktop
- Claude Desktop (or any MCP-compatible client)

## Install

```bash
npx signalpilot@latest init
```

This creates a `signalpilot/` directory with a `docker-compose.yml` and `.env` file.

## Start the gateway

```bash
cd signalpilot
docker compose up -d
```

The MCP server is now running at `http://localhost:8081/mcp`.

## Connect to Claude Desktop

Add this to your Claude Desktop MCP config:

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

Restart Claude Desktop. You should see SignalPilot's 32 tools available.

## Add a database connection

Ask Claude:

> "Connect to my PostgreSQL database at localhost:5432/mydb with user postgres"

Or use the `list_database_connections` tool to see what's already connected.
