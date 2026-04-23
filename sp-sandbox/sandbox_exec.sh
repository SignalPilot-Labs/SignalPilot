#!/bin/sh
# sandbox_exec.sh — privilege-dropping wrapper for sandboxed user code.
#
# Usage: sandbox_exec.sh <timeout_seconds> <cmd> [args...]
#
# Sets CPU-time and file-size ulimits, then drops to nobody (UID 65534)
# via setpriv before exec'ing the given command.
# Note: RLIMIT_AS (ulimit -v) is intentionally NOT set — DuckDB needs
# more virtual address space than a per-process limit allows; the
# container-level mem_limit: 512m is the real enforcement boundary.

set -e

TIMEOUT="$1"
shift

# Validate timeout is a positive integer (defense-in-depth against injection)
case "${TIMEOUT}" in
    ''|*[!0-9]*) echo "sandbox_exec.sh: invalid timeout '${TIMEOUT}'" >&2; exit 1 ;;
esac

# CPU time limit (seconds)
ulimit -t "${TIMEOUT}"

# File size limit: 10 MB
ulimit -f 10240

# Drop to nobody (UID/GID 65534) and exec the command
exec setpriv --reuid=65534 --regid=65534 --init-groups -- "$@"
