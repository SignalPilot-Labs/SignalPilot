#!/usr/bin/env bash
#
# Setup SignalPilot MCP for Claude Code
#
# Usage:
#   ./setup-claude-code.sh                           # localhost:3300, no auth
#   ./setup-claude-code.sh http://myserver:3300       # custom URL
#   ./setup-claude-code.sh http://myserver:3300 sk-.. # custom URL + API key
#
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
SP_URL="${1:-http://localhost:3300}"
SP_KEY="${2:-}"

echo "=== SignalPilot MCP — Claude Code Setup ==="
echo ""
echo "Gateway URL: $SP_URL"
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

if [ -n "$SP_KEY" ]; then
cat <<SETTINGS
{
  "mcpServers": {
    "signalpilot": {
      "command": "signalpilot-mcp-remote",
      "env": {
        "SIGNALPILOT_URL": "$SP_URL",
        "SIGNALPILOT_API_KEY": "$SP_KEY"
      }
    }
  }
}
SETTINGS
else
cat <<SETTINGS
{
  "mcpServers": {
    "signalpilot": {
      "command": "signalpilot-mcp-remote",
      "env": {
        "SIGNALPILOT_URL": "$SP_URL"
      }
    }
  }
}
SETTINGS
fi

echo ""
echo "=== Done ==="
echo "Restart Claude Code to pick up the new MCP server."
