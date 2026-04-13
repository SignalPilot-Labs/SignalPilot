#!/bin/bash
set -e

# ── Run as root: fix permissions on docker-cp'd files ──
chown -R agentuser:agentuser /workspace /signalpilot 2>/dev/null || true
chmod -R u+w /workspace 2>/dev/null || true

# ── Write Claude credentials (as agentuser) ──
if [ -n "$CLAUDE_CODE_OAUTH_TOKEN" ]; then
    echo "[entrypoint] Writing Claude credentials..."
    mkdir -p /home/agentuser/.claude
    cat > /home/agentuser/.claude/.credentials.json <<EOF
{"claudeAiOauth":{"accessToken":"${CLAUDE_CODE_OAUTH_TOKEN}","expiresAt":9999999999999}}
EOF
    chown -R agentuser:agentuser /home/agentuser/.claude
    echo "[entrypoint] Credentials written."
else
    echo "[entrypoint] WARNING: CLAUDE_CODE_OAUTH_TOKEN not set!"
fi

# ── Drop to agentuser and run the benchmark agent ──
exec gosu agentuser python /app/dbt_agent_runner.py "$@"
