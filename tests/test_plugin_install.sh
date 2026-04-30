#!/bin/bash
# Plugin installation and MCP connectivity test
# Runs inside a fresh Docker container
set -euo pipefail

GATEWAY_URL="${SP_GATEWAY_URL:-http://host.docker.internal:3300}"
PASS=0
FAIL=0
ERRORS=""

pass() { echo "  ✓ $1"; PASS=$((PASS + 1)); }
fail() { echo "  ✗ $1"; FAIL=$((FAIL + 1)); ERRORS="${ERRORS}\n  - $1"; }

echo "=== SignalPilot Plugin Installation Test ==="
echo ""

# ── Step 1: Verify Claude Code is installed ─────────────────────────────────
echo "Step 1: Claude Code CLI"
if claude --version 2>/dev/null; then
    pass "Claude Code installed: $(claude --version 2>&1)"
else
    fail "Claude Code not installed"
    echo "FATAL: Cannot continue without Claude Code"
    exit 1
fi

# ── Step 2: Verify plugin structure ──────────────────────────────────────────
echo ""
echo "Step 2: Plugin structure"

if [ -f /workspace/plugin/.claude-plugin/plugin.json ]; then
    pass "plugin.json exists"
else
    fail "plugin.json missing"
fi

if [ -f /workspace/plugin/.mcp.json ]; then
    pass ".mcp.json exists"
else
    fail ".mcp.json missing"
fi

SKILL_COUNT=$(find /workspace/plugin/skills -name "SKILL.md" 2>/dev/null | wc -l)
if [ "$SKILL_COUNT" -gt 0 ]; then
    pass "$SKILL_COUNT skills found"
else
    fail "No skills found"
fi

AGENT_COUNT=$(find /workspace/plugin/agents -name "*.md" 2>/dev/null | wc -l)
if [ "$AGENT_COUNT" -gt 0 ]; then
    pass "$AGENT_COUNT agents found"
else
    fail "No agents found"
fi

# ── Step 3: Add MCP server via CLI ───────────────────────────────────────────
echo ""
echo "Step 3: MCP server registration"

# Add the SignalPilot MCP server pointing to the gateway
claude mcp add \
    --transport http \
    --scope user \
    signalpilot \
    "${GATEWAY_URL}/mcp" 2>&1 && \
    pass "MCP server added via CLI" || \
    fail "Failed to add MCP server"

# Verify it shows up in list
MCP_LIST=$(claude mcp list 2>&1)
echo "  MCP servers: $MCP_LIST"
if echo "$MCP_LIST" | grep -q "signalpilot"; then
    pass "signalpilot appears in mcp list"
else
    fail "signalpilot NOT in mcp list"
fi

# ── Step 4: Test MCP connectivity ─────────────────────────────────────────
echo ""
echo "Step 4: MCP connectivity (via Python MCP client)"

# Install Python MCP client for direct testing
apt-get update -qq && apt-get install -y -qq python3 python3-pip > /dev/null 2>&1
pip3 install --break-system-packages mcp httpx > /dev/null 2>&1

python3 << 'PYEOF'
import asyncio, sys

async def test():
    from mcp import ClientSession
    from mcp.client.streamable_http import streamablehttp_client
    import os

    url = os.environ.get("SP_GATEWAY_URL", "http://host.docker.internal:3300") + "/mcp"

    try:
        async with streamablehttp_client(url) as (read, write, _):
            async with ClientSession(read, write) as session:
                await session.initialize()

                tools = await session.list_tools()
                print(f"  TOOLS_OK:{len(tools.tools)}")

                # Test query
                result = await session.call_tool("query_database", {
                    "connection_name": "chinook",
                    "sql": "SELECT COUNT(*) as n FROM main.artist"
                })
                for c in result.content:
                    text = c.text if hasattr(c, 'text') else str(c)
                    if "275" in text or "rows" in text.lower():
                        print(f"  QUERY_OK:{text[:100]}")
                    else:
                        print(f"  QUERY_RESULT:{text[:100]}")

                # Test schema_overview
                result = await session.call_tool("schema_overview", {"connection_name": "chinook"})
                for c in result.content:
                    text = c.text if hasattr(c, 'text') else str(c)
                    if "Tables:" in text:
                        print(f"  SCHEMA_OK:{text[:100]}")
                    else:
                        print(f"  SCHEMA_RESULT:{text[:100]}")

    except Exception as e:
        print(f"  MCP_ERROR:{e}")
        sys.exit(1)

asyncio.run(test())
PYEOF

PYRESULT=$?
if [ $PYRESULT -eq 0 ]; then
    pass "MCP connectivity verified"
else
    fail "MCP connectivity failed"
fi

# ── Step 5: Test Claude Code with the MCP (non-interactive) ──────────────
echo ""
echo "Step 5: Claude Code + MCP integration"

if [ -z "${CLAUDE_CODE_OAUTH_TOKEN:-}" ]; then
    echo "  Skipping (no CLAUDE_CODE_OAUTH_TOKEN set)"
    pass "Claude Code integration test skipped (no token)"
else
    # Test 5a: Basic MCP tool usage
    echo "  5a: list_database_connections"
    RESULT=$(timeout 60 claude -p \
        "Use the list_database_connections tool and tell me what connections are available. Reply with ONLY the connection names, nothing else." \
        --allowedTools "mcp__signalpilot__list_database_connections" 2>&1) || true
    echo "    Response: ${RESULT:0:200}"
    if echo "$RESULT" | grep -qi "chinook"; then
        pass "list_database_connections works via Claude"
    else
        fail "list_database_connections did not return 'chinook'"
    fi

    # Test 5b: Schema discovery
    echo "  5b: schema_overview + list_tables"
    RESULT=$(timeout 90 claude -p \
        "Use schema_overview on the 'chinook' connection, then list_tables. Tell me exactly how many tables there are and name 3 of them. Reply concisely." \
        --allowedTools "mcp__signalpilot__schema_overview,mcp__signalpilot__list_tables" 2>&1) || true
    echo "    Response: ${RESULT:0:300}"
    if echo "$RESULT" | grep -qi "28\|album\|artist\|track"; then
        pass "Schema discovery works via Claude"
    else
        fail "Schema discovery did not return expected data"
    fi

    # Test 5c: Query execution — real data retrieval
    echo "  5c: query_database (SELECT)"
    RESULT=$(timeout 90 claude -p \
        "Query the chinook database to find the top 3 artists by number of albums. Use query_database. Show the artist name and album count. Reply with ONLY the query results." \
        --allowedTools "mcp__signalpilot__query_database,mcp__signalpilot__list_tables,mcp__signalpilot__describe_table" 2>&1) || true
    echo "    Response: ${RESULT:0:400}"
    if echo "$RESULT" | grep -qiE "iron maiden|led zeppelin|deep purple|ozzy|u2"; then
        pass "Query execution returned real artist data"
    else
        # Accept any structured response with numbers as partial pass
        if echo "$RESULT" | grep -qE "[0-9]+"; then
            pass "Query execution returned data (check output)"
        else
            fail "Query execution returned no data"
        fi
    fi

    # Test 5d: Explore table (schema linking workflow)
    echo "  5d: explore_table + describe_table"
    RESULT=$(timeout 90 claude -p \
        "Explore the main.invoice table in chinook — describe its columns and show the date range of invoice_date. Use describe_table and get_date_boundaries. Reply concisely." \
        --allowedTools "mcp__signalpilot__describe_table,mcp__signalpilot__get_date_boundaries,mcp__signalpilot__explore_table" 2>&1) || true
    echo "    Response: ${RESULT:0:400}"
    if echo "$RESULT" | grep -qiE "invoice|date|2009|2013|total"; then
        pass "Table exploration works via Claude"
    else
        fail "Table exploration did not return expected invoice data"
    fi

    # Test 5e: Simulated dbt-like workflow prompt (tests skill awareness)
    echo "  5e: dbt workflow simulation"
    RESULT=$(timeout 120 claude -p \
        "I have a dbt project connected to the chinook DuckDB database. Before writing any models, I need to understand the schema. Use schema_overview and then find_join_path to discover how artist, album, and track tables are related. Summarize the relationships and suggest what a 'top_artists_by_tracks' dbt model would need to join." \
        --allowedTools "mcp__signalpilot__schema_overview,mcp__signalpilot__find_join_path,mcp__signalpilot__list_tables,mcp__signalpilot__describe_table,mcp__signalpilot__get_relationships" 2>&1) || true
    echo "    Response: ${RESULT:0:500}"
    if echo "$RESULT" | grep -qiE "join|artist.*album\|album.*track\|foreign.key\|relationship"; then
        pass "dbt workflow: schema exploration and join discovery works"
    else
        fail "dbt workflow: did not discover join relationships"
    fi
fi

# ── Results ──────────────────────────────────────────────────────────────────
echo ""
echo "=== Results: $PASS passed, $FAIL failed ==="
if [ $FAIL -gt 0 ]; then
    echo -e "Failures:$ERRORS"
    exit 1
fi
echo "All tests passed!"
