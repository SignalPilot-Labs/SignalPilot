"""
Cloudflare quick-tunnel process manager.

Spawns `cloudflared tunnel --url http://{host}:{port}` as child processes,
parses the assigned public URL from stderr, and monitors process lifetime.

Inside Docker, ports on other containers are reached by service name
(e.g. web:3200 instead of localhost:3200).  The mapping is configured via
the SP_TUNNEL_HOST_MAP env var:  "3200=web,8180=sandbox"
The gateway's own port (3300) always resolves to localhost.
"""

from __future__ import annotations

import asyncio
import logging
import os
import re
import shutil
import signal
import time

from .models import TunnelInfo, TunnelStatus
from .store import upsert_tunnel

logger = logging.getLogger(__name__)

_URL_PATTERN = re.compile(r"(https://[a-zA-Z0-9-]+\.trycloudflare\.com)")

# Graceful stop timeout before SIGKILL
_STOP_TIMEOUT = 5

# Port -> internal hostname mapping for Docker networking.
# Services on the same docker-compose network use their service name.
# Services on a different network (e.g. self-improve) use host.docker.internal
# to reach the port exposed on the Docker host.
# Override with SP_TUNNEL_HOST_MAP env var.
_DEFAULT_HOST_MAP: dict[int, str] = {
    3200: "web",                    # Next.js frontend (same network)
    3400: "host.docker.internal",   # self-improve monitor web (different network)
    3401: "host.docker.internal",   # self-improve monitor API (different network)
    8180: "sandbox",                # firecracker sandbox manager (same network)
}


def _load_host_map() -> dict[int, str]:
    """Build the port->host map from defaults + env override."""
    host_map = dict(_DEFAULT_HOST_MAP)
    raw = os.getenv("SP_TUNNEL_HOST_MAP", "")
    for entry in raw.split(","):
        entry = entry.strip()
        if "=" in entry:
            port_str, host = entry.split("=", 1)
            try:
                host_map[int(port_str.strip())] = host.strip()
            except ValueError:
                pass
    return host_map


def resolve_tunnel_target(port: int) -> str:
    """Return the internal URL that cloudflared should connect to for a given port."""
    host_map = _load_host_map()
    host = host_map.get(port, "localhost")
    # For sandbox, the internal port is 8080 even though it's exposed as 8180
    if port == 8180 and host != "localhost":
        return f"http://{host}:8080"
    return f"http://{host}:{port}"


class TunnelManager:
    """Manages cloudflared child processes."""

    def __init__(self) -> None:
        self._processes: dict[str, asyncio.subprocess.Process] = {}
        self._monitors: dict[str, asyncio.Task[None]] = {}
        self._stopping: set[str] = set()  # tunnels being intentionally stopped

    @staticmethod
    def cloudflared_available() -> bool:
        return shutil.which("cloudflared") is not None

    async def start_tunnel(self, tunnel: TunnelInfo) -> TunnelInfo:
        """Spawn cloudflared and extract the public URL."""
        if not self.cloudflared_available():
            tunnel.status = TunnelStatus.error
            tunnel.error_message = (
                "cloudflared binary not found on PATH. "
                "Install from https://developers.cloudflare.com/cloudflare-one/connections/connect-networks/downloads/"
            )
            upsert_tunnel(tunnel)
            return tunnel

        tunnel.status = TunnelStatus.starting
        tunnel.error_message = None
        upsert_tunnel(tunnel)

        target_url = resolve_tunnel_target(tunnel.local_port)

        try:
            proc = await asyncio.create_subprocess_exec(
                "cloudflared", "tunnel", "--url", target_url,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
        except OSError as e:
            tunnel.status = TunnelStatus.error
            tunnel.error_message = f"Failed to start cloudflared: {e}"
            upsert_tunnel(tunnel)
            return tunnel

        self._processes[tunnel.id] = proc
        tunnel.pid = proc.pid

        # Parse URL from stderr (cloudflared prints it there)
        public_url = await self._extract_url(proc, timeout=20)

        if public_url:
            tunnel.public_url = public_url
            tunnel.status = TunnelStatus.running
            tunnel.started_at = time.time()
            logger.info("Tunnel %s started: %s -> %s", tunnel.id, public_url, target_url)
        else:
            tunnel.status = TunnelStatus.error
            tunnel.error_message = "Timed out waiting for public URL from cloudflared"
            await self._kill_process(tunnel.id)

        upsert_tunnel(tunnel)

        # Start background monitor if process is still alive
        if tunnel.status == TunnelStatus.running:
            task = asyncio.create_task(self._monitor_process(tunnel.id))
            self._monitors[tunnel.id] = task

        return tunnel

    async def stop_tunnel(self, tunnel_id: str) -> bool:
        """Stop a running tunnel process."""
        self._stopping.add(tunnel_id)
        try:
            cancelled = await self._kill_process(tunnel_id)
            # Cancel the monitor task
            monitor = self._monitors.pop(tunnel_id, None)
            if monitor and not monitor.done():
                monitor.cancel()
            return cancelled
        finally:
            self._stopping.discard(tunnel_id)

    async def stop_all(self):
        """Stop all running tunnels (called during gateway shutdown)."""
        tunnel_ids = list(self._processes.keys())
        for tid in tunnel_ids:
            await self.stop_tunnel(tid)

    async def _extract_url(self, proc: asyncio.subprocess.Process, timeout: float) -> str | None:
        """Read stderr lines until we find the trycloudflare.com URL."""
        assert proc.stderr is not None

        async def _read_lines() -> str | None:
            while True:
                line = await proc.stderr.readline()  # type: ignore[union-attr]
                if not line:
                    return None
                text = line.decode("utf-8", errors="replace")
                match = _URL_PATTERN.search(text)
                if match:
                    return match.group(1)

        try:
            return await asyncio.wait_for(_read_lines(), timeout=timeout)
        except asyncio.TimeoutError:
            return None

    async def _kill_process(self, tunnel_id: str) -> bool:
        proc = self._processes.pop(tunnel_id, None)
        if proc is None or proc.returncode is not None:
            return False

        # Try graceful termination first
        try:
            proc.terminate()
        except ProcessLookupError:
            return False

        try:
            await asyncio.wait_for(proc.wait(), timeout=_STOP_TIMEOUT)
        except asyncio.TimeoutError:
            try:
                proc.kill()
                await proc.wait()
            except ProcessLookupError:
                pass

        return True

    async def _monitor_process(self, tunnel_id: str):
        """Watch for unexpected process exit."""
        proc = self._processes.get(tunnel_id)
        if proc is None:
            return

        try:
            returncode = await proc.wait()
        except asyncio.CancelledError:
            return

        # Process exited — clean up
        self._processes.pop(tunnel_id, None)

        # If we intentionally stopped it, the stop_tunnel method handles state
        if tunnel_id in self._stopping:
            return

        from .store import get_tunnel
        tunnel = get_tunnel(tunnel_id)
        if tunnel is None:
            return

        tunnel.status = TunnelStatus.error
        tunnel.error_message = f"cloudflared exited unexpectedly (code {returncode})"
        tunnel.pid = None
        tunnel.public_url = None
        upsert_tunnel(tunnel)
        logger.warning("Tunnel %s died with code %d", tunnel_id, returncode)
