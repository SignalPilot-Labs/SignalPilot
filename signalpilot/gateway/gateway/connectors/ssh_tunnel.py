"""SSH tunnel manager — wraps sshtunnel for secure bastion-host connections.

Implements the industry-standard two-phase connection pattern:
1. Establish SSH tunnel to bastion host
2. Connect to database through the tunnel's local port

Supports password, private key, and ssh-agent authentication.
HTTP proxy support for corporate VPCs that block direct SSH (HEX pattern).
"""

from __future__ import annotations

import io
import logging
import re
import shlex
from typing import Any

logger = logging.getLogger(__name__)

try:
    from sshtunnel import SSHTunnelForwarder

    HAS_SSHTUNNEL = True
except ImportError:
    HAS_SSHTUNNEL = False


_HOSTNAME_RE = re.compile(r'^[a-zA-Z0-9.\-:]+$')


def _validate_hostname(value: str, field: str) -> None:
    """Raise ValueError if value contains characters outside the safe hostname set."""
    if not _HOSTNAME_RE.match(value):
        raise ValueError(
            f"Invalid {field} {value!r}: only alphanumeric characters, dots, "
            "hyphens, and colons are allowed"
        )


def _build_proxy_command(proxy_host: str, proxy_port: int, ssh_host: str, ssh_port: int) -> str:
    """Build a ProxyCommand string for HTTP CONNECT proxy tunneling.

    This enables SSH through corporate HTTP proxies (e.g. Squid) that support
    the CONNECT method — common in VPC environments where direct SSH is blocked.
    """
    _validate_hostname(proxy_host, "proxy_host")
    _validate_hostname(ssh_host, "ssh_host")
    # Use shlex.quote for defense-in-depth even after validation
    return (
        f"socat - PROXY:{shlex.quote(proxy_host)}:{shlex.quote(ssh_host)}"
        f":{ssh_port},proxyport={proxy_port}"
    )


class SSHTunnel:
    """Manages an SSH tunnel for a single database connection."""

    def __init__(self, config: dict[str, Any]):
        if not HAS_SSHTUNNEL:
            raise RuntimeError("sshtunnel not installed. Run: pip install sshtunnel")

        self._config = config
        self._tunnel: SSHTunnelForwarder | None = None

    def start(self, remote_host: str, remote_port: int) -> tuple[str, int]:
        """Open SSH tunnel and return (local_bind_host, local_bind_port).

        The caller should connect to the returned local address instead of
        the original remote_host:remote_port.
        """
        ssh_host = self._config.get("host")
        ssh_port = self._config.get("port", 22)
        ssh_username = self._config.get("username")

        if not ssh_host or not ssh_username:
            raise ValueError("SSH tunnel requires host and username")

        _validate_hostname(ssh_host, "ssh_host")
        _validate_hostname(remote_host, "remote_host")

        tunnel_kwargs: dict[str, Any] = {
            "ssh_address_or_host": (ssh_host, ssh_port),
            "ssh_username": ssh_username,
            "remote_bind_address": (remote_host, remote_port),
            "local_bind_address": ("127.0.0.1", 0),  # OS picks a free port
            "set_keepalive": 60,  # Keep-alive every 60s (industry standard)
        }

        # HTTP proxy support (HEX pattern) — for VPCs that block direct SSH
        proxy_host = self._config.get("proxy_host")
        proxy_port = self._config.get("proxy_port", 3128)
        if proxy_host:
            import paramiko
            proxy_cmd = _build_proxy_command(proxy_host, proxy_port, ssh_host, ssh_port)
            sock = paramiko.ProxyCommand(proxy_cmd)
            tunnel_kwargs["ssh_proxy"] = sock
            logger.info("SSH tunnel using HTTP proxy: %s:%d", proxy_host, proxy_port)

        auth_method = self._config.get("auth_method", "password")
        if auth_method == "key" and self._config.get("private_key"):
            # Private key auth — parse PEM from string
            import paramiko

            pkey_str = self._config["private_key"]
            passphrase = self._config.get("private_key_passphrase")

            # Try RSA first, then Ed25519, then ECDSA
            pkey = None
            for key_class in [paramiko.RSAKey, paramiko.Ed25519Key, paramiko.ECDSAKey]:
                try:
                    pkey = key_class.from_private_key(
                        io.StringIO(pkey_str),
                        password=passphrase,
                    )
                    break
                except Exception:
                    continue

            if pkey is None:
                raise ValueError(
                    "Could not parse SSH private key. Supported formats: RSA, Ed25519, ECDSA"
                )

            tunnel_kwargs["ssh_pkey"] = pkey
        elif auth_method == "agent":
            # ssh-agent forwarding — use keys loaded in the agent
            tunnel_kwargs["allow_agent"] = True
            logger.info("SSH tunnel using ssh-agent for authentication")
        else:
            # Password auth
            password = self._config.get("password")
            if not password:
                raise ValueError("SSH tunnel with password auth requires a password")
            tunnel_kwargs["ssh_password"] = password

        self._tunnel = SSHTunnelForwarder(**tunnel_kwargs)
        self._tunnel.start()

        local_host = self._tunnel.local_bind_host
        local_port = self._tunnel.local_bind_port

        logger.info(
            "SSH tunnel established: %s:%d -> %s:%d via %s@%s:%d",
            local_host,
            local_port,
            remote_host,
            remote_port,
            ssh_username,
            ssh_host,
            ssh_port,
        )

        return local_host, local_port

    def stop(self):
        """Close the SSH tunnel."""
        if self._tunnel:
            try:
                self._tunnel.stop()
            except Exception as e:
                logger.warning("Error stopping SSH tunnel: %s", e)
            self._tunnel = None

    @property
    def is_active(self) -> bool:
        return self._tunnel is not None and self._tunnel.is_active

    def check_tunnel(self) -> bool:
        """Verify the tunnel is still active."""
        if self._tunnel is None:
            return False
        try:
            return self._tunnel.is_active
        except Exception:
            return False
