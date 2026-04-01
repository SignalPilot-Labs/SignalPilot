#!/bin/bash
set -e

# Fix docker socket permissions so agentuser can use Docker CLI.
if [ -S /var/run/docker.sock ]; then
    chmod 666 /var/run/docker.sock
fi

exec gosu agentuser "$@"
