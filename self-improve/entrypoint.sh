#!/bin/bash
set -e

# Authenticate Claude CLI using the OAuth token
# CLAUDE_CODE_OAUTH_TOKEN is passed as env var, never written to disk
if [ -n "$CLAUDE_CODE_OAUTH_TOKEN" ]; then
    echo "[entrypoint] Authenticating Claude CLI..."
    echo "$CLAUDE_CODE_OAUTH_TOKEN" | claude setup --token - 2>/dev/null || \
    claude setup --token "$CLAUDE_CODE_OAUTH_TOKEN" 2>/dev/null || \
    echo "[entrypoint] Warning: Claude CLI auth may have failed, SDK will try ANTHROPIC_API_KEY fallback"
fi

# Agent code lives in /app, but working_dir is /workspace for git ops
export PYTHONPATH="/app:$PYTHONPATH"

# Run the agent
exec python -m agent.main "$@"
