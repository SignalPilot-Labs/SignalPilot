"""Tests for cloud-mode SSRF validation of SSH tunnel bastion/proxy hosts.

Covers the _validate_connection_params path in
gateway.api.connections._validation for ssh_tunnel.host and
ssh_tunnel.proxy_host.

_validate_connection_params is imported lazily via importlib to bypass the
gateway.api.__init__ FastAPI import (which is not installed in this test
environment).
"""

from __future__ import annotations

import importlib.util
import types
from pathlib import Path
from typing import Any
from unittest.mock import patch

import pytest


def _load_validation_module() -> Any:
    """Load gateway.api.connections._validation directly without triggering
    gateway.api or gateway.api.connections package __init__ files (which
    require FastAPI, not available in this test environment)."""
    import sys

    # Stub out the parent packages if not already loaded so that
    # gateway.models and gateway.network (the only real deps of _validation.py)
    # import cleanly without triggering the FastAPI-dependent __init__ files.
    for pkg in ("gateway.api", "gateway.api.connections"):
        if pkg not in sys.modules:
            sys.modules[pkg] = types.ModuleType(pkg)

    spec = importlib.util.spec_from_file_location(
        "gateway.api.connections._validation",
        Path(__file__).parent.parent / "gateway" / "api" / "connections" / "_validation.py",
    )
    assert spec is not None and spec.loader is not None
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)  # type: ignore[union-attr]
    return mod


_VALIDATION_MOD = _load_validation_module()
_validate_connection_params = _VALIDATION_MOD._validate_connection_params


def _patch_dns(resolved_ip: str):
    """Patch socket.getaddrinfo to return a single resolved IP."""
    return patch(
        "gateway.network.validation.socket.getaddrinfo",
        return_value=[(None, None, None, None, (resolved_ip, 0))],
    )


def _make_postgres_conn_with_ssh(ssh_host: str, proxy_host: str | None = None):
    """Build a minimal postgres ConnectionCreate with SSH tunnel enabled."""
    from gateway.models import ConnectionCreate, SSHTunnelConfig

    tunnel = SSHTunnelConfig(
        enabled=True,
        host=ssh_host,
        username="tunnel-user",
        auth_method="password",
        password="s3cret",
        proxy_host=proxy_host,
    )
    return ConnectionCreate(
        name="test-conn",
        db_type="postgres",
        host="db.example.com",
        port=5432,
        username="dbuser",
        password="dbpass",
        database="mydb",
        ssh_tunnel=tunnel,
    )


class TestSshTunnelCloudModeBastion:
    def test_imds_bastion_host_rejected_in_cloud_mode(self, monkeypatch):
        """169.254.169.254 as SSH bastion host must produce an error in cloud mode."""
        monkeypatch.setenv("SP_DEPLOYMENT_MODE", "cloud")
        conn = _make_postgres_conn_with_ssh("169.254.169.254")
        with _patch_dns("169.254.169.254"):
            errors = _validate_connection_params(conn)
        assert errors, "Expected errors for IMDS bastion host"
        assert any("bastion" in e.lower() for e in errors)

    def test_loopback_bastion_host_rejected_in_cloud_mode(self, monkeypatch):
        """127.0.0.1 as SSH bastion host must produce an error in cloud mode."""
        monkeypatch.setenv("SP_DEPLOYMENT_MODE", "cloud")
        conn = _make_postgres_conn_with_ssh("127.0.0.1")
        with _patch_dns("127.0.0.1"):
            errors = _validate_connection_params(conn)
        assert errors, "Expected errors for loopback bastion host"
        assert any("bastion" in e.lower() for e in errors)

    def test_public_bastion_host_allowed_in_cloud_mode(self, monkeypatch):
        """A public-resolving bastion host must not produce SSH-tunnel errors."""
        monkeypatch.setenv("SP_DEPLOYMENT_MODE", "cloud")
        conn = _make_postgres_conn_with_ssh("bastion.example.com")
        # Patch validate_connection_host on the loaded module to avoid live DNS
        with patch.object(_VALIDATION_MOD, "validate_connection_host"):
            with _patch_dns("52.0.0.1"):
                errors = _validate_connection_params(conn)
        ssh_errors = [e for e in errors if "bastion" in e.lower() or "proxy" in e.lower()]
        assert not ssh_errors, f"Unexpected SSH-tunnel errors: {ssh_errors}"

    def test_bastion_host_validation_skipped_in_local_mode(self, monkeypatch):
        """In local mode, bastion host SSRF validation must be skipped entirely."""
        monkeypatch.setenv("SP_DEPLOYMENT_MODE", "local")
        conn = _make_postgres_conn_with_ssh("10.0.0.1")
        # In local mode validate_connection_params also skips SSRF for all hosts
        with _patch_dns("10.0.0.1"):
            errors = _validate_connection_params(conn)
        ssh_errors = [e for e in errors if "bastion" in e.lower() or "proxy" in e.lower()]
        assert not ssh_errors, f"Unexpected SSH-tunnel SSRF errors in local mode: {ssh_errors}"


class TestSshTunnelCloudModeProxy:
    def test_imds_proxy_host_rejected_in_cloud_mode(self, monkeypatch):
        """169.254.169.254 as SSH HTTP proxy host must produce an error in cloud mode."""
        monkeypatch.setenv("SP_DEPLOYMENT_MODE", "cloud")
        conn = _make_postgres_conn_with_ssh("bastion.example.com", proxy_host="169.254.169.254")

        def _fake_validate_host(host: str) -> None:
            if host == "169.254.169.254":
                raise ValueError("169.254.169.254 is a blocked link-local address")
            # bastion.example.com passes

        with patch.object(_VALIDATION_MOD, "validate_connection_host", side_effect=_fake_validate_host):
            with _patch_dns("52.0.0.1"):
                errors = _validate_connection_params(conn)
        assert errors, "Expected errors for IMDS proxy host"
        assert any("proxy" in e.lower() for e in errors)

    def test_loopback_proxy_host_rejected_in_cloud_mode(self, monkeypatch):
        """127.0.0.1 as SSH HTTP proxy host must produce an error in cloud mode."""
        monkeypatch.setenv("SP_DEPLOYMENT_MODE", "cloud")
        conn = _make_postgres_conn_with_ssh("bastion.example.com", proxy_host="127.0.0.1")

        def _fake_validate_host(host: str) -> None:
            if host == "127.0.0.1":
                raise ValueError("127.0.0.1 is a blocked loopback address")

        with patch.object(_VALIDATION_MOD, "validate_connection_host", side_effect=_fake_validate_host):
            with _patch_dns("52.0.0.1"):
                errors = _validate_connection_params(conn)
        assert errors, "Expected errors for loopback proxy host"
        assert any("proxy" in e.lower() for e in errors)
