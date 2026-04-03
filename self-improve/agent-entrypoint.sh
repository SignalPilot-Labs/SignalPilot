#!/bin/bash
set -e

# Docker socket is no longer mounted directly — agent uses DOCKER_HOST=tcp://docker-proxy:2375
# No chmod needed.

# Fix repo volume ownership (created as root on first run)
if [ -d /home/agentuser/repo ]; then
    chown agentuser:agentuser /home/agentuser/repo
fi

# Ensure shared data volume is writable by agentuser
if [ -d /data ]; then
    chown -R agentuser:agentuser /data 2>/dev/null || true
else
    mkdir -p /data && chown agentuser:agentuser /data
fi

exec gosu agentuser "$@"
