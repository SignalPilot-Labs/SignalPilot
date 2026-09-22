"""In-sandbox SSH tunnel for the dbt executor sandbox.

The gateway reaches bastion-fronted warehouses through
``connectors.ssh_tunnel`` (sshtunnel + paramiko in the gateway process). The
dbt executor runs on a Vercel sandbox that has no network path back through
the gateway, so the same forwarder has to run inside the sandbox. The notebook
image ships no ssh binary, so this module runs a pure-Python forwarder there:

1. ``plan_tunnel`` reads the connection's credential extras, validates the
   bastion config, picks a fixed local port and rewrites the DSN to point at
   ``127.0.0.1:<local_port>`` so the emitted dbt profile targets the forward.
2. ``start_tunnel`` writes the tunnel material to ``/creds/ssh_tunnel.json``
   (mode 600) plus a small forwarder script, starts it in the background and
   waits for ``/creds/tunnel.ready``.
3. ``ensure_tunnel_alive`` re-checks a reused executor before every dbt run and
   relaunches the forwarder when the sandbox was resumed or the tunnel dropped.

Everything under ``/creds`` is outside ``/workspace`` so project syncs never
carry the material. Key material and passwords are never logged.
"""

from __future__ import annotations

import asyncio
import json
import logging
import shlex
import time
from dataclasses import dataclass, field

from ..connectors.pool_manager import (
    _DEFAULT_PORTS,
    _TUNNEL_CAPABLE_DB_TYPES,
    _extract_host_port,
    _rewrite_connection_string,
)
from ..connectors.ssh_tunnel import _build_proxy_command, _validate_socat_host, _validate_socat_port
from ..models.connections import SSHTunnelConfig

logger = logging.getLogger(__name__)

CREDS_DIR = "/creds"
TUNNEL_CONFIG_PATH = f"{CREDS_DIR}/ssh_tunnel.json"
TUNNEL_SCRIPT_PATH = f"{CREDS_DIR}/sp_tunnel.py"
TUNNEL_READY_PATH = f"{CREDS_DIR}/tunnel.ready"
TUNNEL_LOG_PATH = f"{CREDS_DIR}/tunnel.log"
LOCAL_BIND_HOST = "127.0.0.1"

_VENV_BIN = "/opt/sp-notebook/.venv/bin"
# Fixed local port per db type: the warehouse default plus this offset, so the
# forward never collides with a service the image itself might bind.
_LOCAL_PORT_OFFSET = 10000
_READY_TIMEOUT_SECONDS = 30.0
_READY_POLL_SECONDS = 0.5
_LOG_TAIL_CHARS = 600


class DbtTunnelError(RuntimeError):
    pass


@dataclass(frozen=True)
class TunnelPlan:
    """What the executor needs to know. ``material`` is the full JSON payload
    for the sandbox and is excluded from repr so it can never leak via logs."""

    db_type: str
    local_port: int
    remote_host: str
    remote_port: int
    dsn: str = field(repr=False)
    material: dict = field(repr=False)


def local_port_for(db_type: str) -> int:
    return _DEFAULT_PORTS.get(db_type, 5432) + _LOCAL_PORT_OFFSET


def plan_tunnel(db_type: str, dsn: str, extras: dict | None) -> TunnelPlan | None:
    """Return a TunnelPlan when the connection has an enabled SSH tunnel, else
    None. Validation failures raise DbtTunnelError before anything reaches the
    sandbox."""
    raw = (extras or {}).get("ssh_tunnel")
    if not isinstance(raw, dict) or not raw.get("enabled"):
        return None
    cfg = SSHTunnelConfig.model_validate(raw)
    if db_type not in _TUNNEL_CAPABLE_DB_TYPES:
        raise DbtTunnelError(
            f"SSH tunnels are not supported for '{db_type}' connections in dbt_execute "
            f"(supported: {', '.join(sorted(_TUNNEL_CAPABLE_DB_TYPES))})."
        )
    if cfg.auth_method == "agent":
        raise DbtTunnelError(
            "SSH tunnel auth_method 'agent' is not available inside the dbt sandbox; "
            "there is no ssh-agent there. Use key or password authentication."
        )
    if not cfg.host or not cfg.username:
        raise DbtTunnelError("SSH tunnel requires host and username")
    if cfg.auth_method == "key" and not cfg.private_key:
        raise DbtTunnelError("SSH tunnel with key auth requires a private key")
    if cfg.auth_method == "password" and not cfg.password:
        raise DbtTunnelError("SSH tunnel with password auth requires a password")
    try:
        ssh_host = _validate_socat_host("ssh_host", cfg.host)
        ssh_port = _validate_socat_port("ssh_port", cfg.port)
        proxy_command = (
            _build_proxy_command(cfg.proxy_host, cfg.proxy_port, ssh_host, ssh_port) if cfg.proxy_host else None
        )
    except ValueError as exc:
        raise DbtTunnelError(f"SSH tunnel configuration rejected: {exc}") from exc

    remote_host, remote_port = _extract_host_port(dsn, db_type)
    local_port = local_port_for(db_type)
    material = {
        "ssh_host": ssh_host,
        "ssh_port": ssh_port,
        "ssh_username": cfg.username,
        "auth_method": cfg.auth_method,
        "password": cfg.password,
        "private_key": cfg.private_key,
        "private_key_passphrase": cfg.private_key_passphrase,
        "proxy_command": proxy_command,
        "remote_host": remote_host,
        "remote_port": remote_port,
        "local_port": local_port,
    }
    return TunnelPlan(
        db_type=db_type,
        local_port=local_port,
        remote_host=remote_host,
        remote_port=remote_port,
        dsn=_rewrite_connection_string(dsn, db_type, LOCAL_BIND_HOST, local_port),
        material=material,
    )


# The forwarder that runs inside the sandbox. Kept dependency-light: only
# paramiko and sshtunnel, both baked into the notebook image (and pip-installed
# as a fallback by start_tunnel). Key-loading order matches connectors/ssh_tunnel.
FORWARDER_SCRIPT = r'''"""SignalPilot in-sandbox SSH forwarder. Written by the gateway; do not edit."""
import io
import json
import os
import shutil
import sys
import time

import paramiko
from sshtunnel import SSHTunnelForwarder

CONFIG = "/creds/ssh_tunnel.json"
READY = "/creds/tunnel.ready"


def fail(message, code=2):
    sys.stderr.write("sp_tunnel: " + message + "\n")
    sys.stderr.flush()
    if os.path.exists(READY):
        os.remove(READY)
    sys.exit(code)


def load_key(pem, passphrase):
    for key_class in (paramiko.RSAKey, paramiko.Ed25519Key, paramiko.ECDSAKey):
        try:
            return key_class.from_private_key(io.StringIO(pem), password=passphrase or None)
        except Exception:
            continue
    fail("could not parse SSH private key (supported formats: RSA, Ed25519, ECDSA)")


def build(cfg):
    kwargs = {
        "ssh_address_or_host": (cfg["ssh_host"], int(cfg["ssh_port"])),
        "ssh_username": cfg["ssh_username"],
        "remote_bind_address": (cfg["remote_host"], int(cfg["remote_port"])),
        "local_bind_address": ("127.0.0.1", int(cfg["local_port"])),
        "set_keepalive": 60,
    }
    method = cfg.get("auth_method") or "password"
    if method == "key":
        kwargs["ssh_pkey"] = load_key(cfg.get("private_key") or "", cfg.get("private_key_passphrase"))
    elif method == "password":
        if not cfg.get("password"):
            fail("password auth requires a password")
        kwargs["ssh_password"] = cfg["password"]
    else:
        fail("auth_method '%s' is not available inside the dbt sandbox (no ssh-agent)" % method)
    proxy_command = cfg.get("proxy_command")
    if proxy_command:
        if shutil.which("socat") is None:
            fail("proxy_host requires socat, which this sandbox image does not ship")
        kwargs["ssh_proxy"] = paramiko.ProxyCommand(proxy_command)
    return SSHTunnelForwarder(**kwargs)


def main():
    with open(CONFIG) as fh:
        cfg = json.load(fh)
    tunnel = build(cfg)
    tunnel.start()
    if not tunnel.is_active:
        fail("tunnel did not become active")
    tmp = READY + ".tmp"
    with open(tmp, "w") as fh:
        fh.write("READY %d\n" % tunnel.local_bind_port)
    os.replace(tmp, READY)
    while True:
        time.sleep(30)
        if not tunnel.is_active:
            fail("tunnel dropped", code=3)


if __name__ == "__main__":
    main()
'''


def _launch_command() -> str:
    python = f"{_VENV_BIN}/python"
    return (
        f"rm -f {TUNNEL_READY_PATH} {TUNNEL_LOG_PATH}; "
        f"exec {python} {TUNNEL_SCRIPT_PATH} >{TUNNEL_LOG_PATH} 2>&1"
    )


def _liveness_command(local_port: int) -> str:
    # bash's /dev/tcp gives a real connect() without needing nc or curl.
    return (
        f"grep -q '^READY' {TUNNEL_READY_PATH} && "
        f"timeout 3 bash -c 'exec 3<>/dev/tcp/{LOCAL_BIND_HOST}/{int(local_port)}'"
    )


async def _log_tail(runtime, sandbox_id: str) -> str:
    try:
        data = await runtime.read_file(sandbox_id, TUNNEL_LOG_PATH)
    except Exception:
        data = None
    text = (data or b"").decode("utf-8", errors="replace").strip()
    return text[-_LOG_TAIL_CHARS:]


async def _launch_and_wait(runtime, sandbox_id: str, local_port: int) -> None:
    await runtime.start_process(sandbox_id, _launch_command())
    deadline = time.monotonic() + _READY_TIMEOUT_SECONDS
    while time.monotonic() < deadline:
        probe = await runtime.exec(sandbox_id, f"cat {TUNNEL_READY_PATH}", timeout_seconds=10)
        if probe.ok and probe.stdout.strip().startswith("READY"):
            logger.info("dbt executor SSH tunnel ready on %s:%d", LOCAL_BIND_HOST, local_port)
            return
        await asyncio.sleep(_READY_POLL_SECONDS)
    tail = await _log_tail(runtime, sandbox_id)
    raise DbtTunnelError(
        f"SSH tunnel did not come up within {int(_READY_TIMEOUT_SECONDS)}s. "
        f"Forwarder output: {tail or '<empty>'}"
    )


async def start_tunnel(runtime, sandbox_id: str, plan: TunnelPlan) -> None:
    """Install the forwarder's dependencies, write the material and script under
    /creds, launch the forwarder and wait until it is listening."""
    install = await runtime.exec(
        sandbox_id,
        f'export PATH="{_VENV_BIN}:$PATH"; '
        "(pip show sshtunnel >/dev/null 2>&1 && pip show paramiko >/dev/null 2>&1) "
        "|| pip install --quiet sshtunnel paramiko",
        timeout_seconds=300,
    )
    if not install.ok:
        raise DbtTunnelError(f"could not install the SSH forwarder: {install.stderr[-300:]}")
    await runtime.write_file(sandbox_id, TUNNEL_CONFIG_PATH, json.dumps(plan.material).encode())
    await runtime.write_file(sandbox_id, TUNNEL_SCRIPT_PATH, FORWARDER_SCRIPT.encode())
    perms = await runtime.exec(
        sandbox_id,
        f"chmod 600 {shlex.quote(TUNNEL_CONFIG_PATH)} && chmod 700 {shlex.quote(CREDS_DIR)}",
        timeout_seconds=10,
    )
    if not perms.ok:
        raise DbtTunnelError(f"could not secure the tunnel material: {perms.stderr[-200:]}")
    logger.info(
        "starting dbt executor SSH tunnel for %s: %s:%d -> %s@%s:%d",
        plan.db_type, LOCAL_BIND_HOST, plan.local_port,
        plan.material["ssh_username"], plan.material["ssh_host"], plan.material["ssh_port"],
    )
    await _launch_and_wait(runtime, sandbox_id, plan.local_port)


async def ensure_tunnel_alive(runtime, sandbox_id: str, local_port: int) -> bool:
    """Verify a reused executor's forwarder still accepts connections; relaunch
    it from the material already under /creds when it does not. Returns True
    when a relaunch happened."""
    probe = await runtime.exec(sandbox_id, _liveness_command(local_port), timeout_seconds=10)
    if probe.ok:
        return False
    logger.info("dbt executor SSH tunnel on port %d is down; relaunching", local_port)
    await _launch_and_wait(runtime, sandbox_id, local_port)
    return True
