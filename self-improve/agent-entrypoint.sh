#!/bin/bash
set -e

# Fix docker socket permissions so agentuser can use Docker CLI.
if [ -S /var/run/docker.sock ]; then
    chmod 666 /var/run/docker.sock
fi

# Fix repo volume ownership (created as root on first run)
if [ -d /home/agentuser/repo ]; then
    chown agentuser:agentuser /home/agentuser/repo
fi

# Ensure shared data volume is writable by agentuser
if [ -d /data ]; then
    chown -R agentuser:agentuser /data 2>/dev/null || chmod -R a+rw /data 2>/dev/null || true
else
    mkdir -p /data && chown agentuser:agentuser /data
fi

exec gosu agentuser "$@"
