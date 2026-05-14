#!/usr/bin/env python3
"""Fake sandbox server for testing SubprocessSpawner.

Prints a few lines to stdout and stderr, sleeps for
FAKE_SANDBOX_LIFETIME_SECONDS (default 0.5), then exits with code from
FAKE_SANDBOX_EXIT_CODE (default 0).

Tests override settings.sp_sandbox_server_path to point at this file.
"""
import os
import sys
import time

_internal_secret = os.environ.pop("AGENT_INTERNAL_SECRET", "")
if not _internal_secret:
    print("ERROR: AGENT_INTERNAL_SECRET missing", file=sys.stderr)
    sys.exit(1)

lifetime = float(os.environ.get("FAKE_SANDBOX_LIFETIME_SECONDS", "0.5"))
exit_code = int(os.environ.get("FAKE_SANDBOX_EXIT_CODE", "0"))

print("fake_sandbox: starting up", flush=True)
print("fake_sandbox: ready", flush=True)
print("fake_sandbox: stderr line", file=sys.stderr, flush=True)

time.sleep(lifetime)

print("fake_sandbox: shutting down", flush=True)
sys.exit(exit_code)
