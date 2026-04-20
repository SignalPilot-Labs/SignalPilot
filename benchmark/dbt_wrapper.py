#!/usr/bin/env python3
"""dbt wrapper that blocks outbound network and uses faketime for current_date.

dbt makes HTTPS calls (telemetry, version check, hub registry) that hang
when libfaketime is active because TLS certificates appear "not yet valid".
This wrapper monkey-patches socket.connect to reject all non-local connections,
then delegates to dbt's real CLI entry point.
"""
import os
import socket
import sys

# Block all outbound TCP connections (dbt doesn't need network for local builds)
_orig_connect = socket.socket.connect

def _blocked_connect(self, address):
    # Block all remote TCP connections. Allow only:
    # - Unix sockets (AF_UNIX) — used by multiprocessing, resource_tracker
    # - Localhost connections — used by DuckDB adapter internals
    if self.family in (socket.AF_INET, socket.AF_INET6) and isinstance(address, tuple):
        host = address[0]
        if host not in ("127.0.0.1", "localhost", "::1", "0.0.0.0"):
            raise OSError(f"[dbt-network-block] Connection to {host} blocked")
    return _orig_connect(self, address)

socket.socket.connect = _blocked_connect

# Set env vars that dbt checks (belt and suspenders)
os.environ["DO_NOT_TRACK"] = "1"
os.environ["DBT_NO_VERSION_CHECK"] = "1"

# Run dbt CLI
from dbt.cli.main import cli
cli()
