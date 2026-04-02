#!/usr/bin/env bash
#
# Setup SignalPilot MCP for Claude Code
#
# Usage:
#   ./setup-claude-code.sh                                          # localhost defaults
#   ./setup-claude-code.sh http://myserver:3300                     # custom gateway
#   ./setup-claude-code.sh http://myserver:3300 http://myserver:3401  # custom gateway + monitor
#   ./setup-claude-code.sh http://myserver:3300 http://myserver:3401 sk-..  # + API key
#
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
SP_URL="${1:-http://localhost:3300}"
SP_MONITOR="${2:-http://localhost:3401}"
SP_KEY="${3:-}"

# Auto-derive monitor URL from gateway URL if only gateway provided
if [ "$#" -eq 1 ]; then
    # Strip trailing slash, then replace port (or append :3401 if no port)
    CLEAN_URL="$(echo "$SP_URL" | sed 's|/\+$||')"
    if echo "$CLEAN_URL" | grep -qE ':[0-9]+$'; then
        SP_MONITOR="$(echo "$CLEAN_URL" | sed 's|:[0-9]*$|:3401|')"
    else
        SP_MONITOR="${CLEAN_URL}:3401"
    fi
fi

echo "=== SignalPilot MCP — Claude Code Setup ==="
echo ""
echo "Gateway URL: $SP_URL"
echo "Monitor URL: $SP_MONITOR"
[ -n "$SP_KEY" ] && echo "API Key:     (set)" || echo "API Key:     (none)"
echo ""

# 1. Install the package
echo "Installing signalpilot-mcp..."
pip install -e "$SCRIPT_DIR" --quiet 2>/dev/null || pip install -e "$SCRIPT_DIR"
echo "Installed."

# 2. Verify it runs
if command -v signalpilot-mcp-remote &>/dev/null; then
    echo "Binary: $(which signalpilot-mcp-remote)"
else
    echo "Warning: signalpilot-mcp-remote not found in PATH."
    echo "You may need to add your pip scripts directory to PATH."
fi

# 3. Generate the Claude Code settings snippet
echo ""
echo "=== Add this to your Claude Code settings ==="
echo ""
echo "File: ~/.claude/settings.json (global) or .claude/settings.json (per-project)"
echo ""

ENV_BLOCK="\"SIGNALPILOT_URL\": \"$SP_URL\",
        \"SIGNALPILOT_MONITOR_URL\": \"$SP_MONITOR\""
if [ -n "$SP_KEY" ]; then
    ENV_BLOCK="$ENV_BLOCK,
        \"SIGNALPILOT_API_KEY\": \"$SP_KEY\""
fi

cat <<SETTINGS
{
  "mcpServers": {
    "signalpilot": {
      "command": "signalpilot-mcp-remote",
      "env": {
        $ENV_BLOCK
      }
    }
  }
}
SETTINGS

echo ""
echo "=== Done ==="
echo "Restart Claude Code to pick up the new MCP server."
echo ""
echo "Try these in Claude Code:"
echo '  "Check the agent status"'
echo '  "Start an improvement run focused on test coverage for 30 minutes"'
echo '  "Show me the latest improvement run output"'
