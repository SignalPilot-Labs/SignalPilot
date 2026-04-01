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

exec gosu agentuser "$@"
