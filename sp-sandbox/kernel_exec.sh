#!/bin/sh
# kernel_exec.sh — privilege-dropping wrapper for the kernel process.
#
# Like sandbox_exec.sh but without CPU time limit (kernel is long-lived).
# Sets file-size ulimit, then drops to nobody (UID 65534).

set -e

# File size limit: 10 MB
ulimit -f 10240

# Drop to nobody (UID/GID 65534) and exec the kernel
exec setpriv --reuid=65534 --regid=65534 --init-groups -- "$@"
