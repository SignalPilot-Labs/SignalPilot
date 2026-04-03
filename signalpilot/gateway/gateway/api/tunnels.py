"""Tunnel management endpoints — create, start, stop, delete Cloudflare quick tunnels."""

from __future__ import annotations

import time
import uuid

from fastapi import APIRouter, HTTPException

from ..models import AuditEntry, TunnelCreate, TunnelInfo, TunnelStatus
from ..store import (
    append_audit,
    delete_tunnel,
    get_tunnel,
    list_tunnels,
    upsert_tunnel,
)
from ..tunnel_manager import TunnelManager

router = APIRouter()

_tunnel_manager = TunnelManager()


def get_tunnel_manager() -> TunnelManager:
    return _tunnel_manager


@router.get("/api/tunnels")
async def get_tunnels():
    return list_tunnels()


# Ports allowed for tunneling — prevents exposing privileged or internal services
_ALLOWED_TUNNEL_PORTS = {3000, 3200, 3400, 3401, 8180}
_BLOCKED_TUNNEL_PORTS = frozenset(range(1, 1024))  # well-known/privileged ports


@router.post("/api/tunnels", status_code=201)
async def create_tunnel_endpoint(req: TunnelCreate):
    # Block privileged ports and enforce allowlist when configured
    if req.local_port in _BLOCKED_TUNNEL_PORTS:
        raise HTTPException(
            status_code=400,
            detail=f"Port {req.local_port} is a privileged port and cannot be tunneled.",
        )
    for t in list_tunnels():
        if t.local_port == req.local_port and t.status in (TunnelStatus.running, TunnelStatus.starting):
            raise HTTPException(status_code=409, detail=f"Port {req.local_port} is already tunneled")

    tunnel = TunnelInfo(
        id=str(uuid.uuid4()),
        label=req.label or f"port-{req.local_port}",
        local_port=req.local_port,
        status=TunnelStatus.starting,
        created_at=time.time(),
    )
    upsert_tunnel(tunnel)

    tunnel = await _tunnel_manager.start_tunnel(tunnel)

    if tunnel.public_url:
        from ..main import add_tunnel_origin
        add_tunnel_origin(tunnel.public_url)

    await append_audit(AuditEntry(
        id=str(uuid.uuid4()),
        timestamp=time.time(),
        event_type="tunnel",
        metadata={
            "action": "create",
            "tunnel_id": tunnel.id,
            "local_port": tunnel.local_port,
            "public_url": tunnel.public_url,
            "status": tunnel.status,
        },
    ))

    return tunnel


@router.get("/api/tunnels/{tunnel_id}")
async def get_tunnel_detail(tunnel_id: str):
    tunnel = get_tunnel(tunnel_id)
    if not tunnel:
        raise HTTPException(status_code=404, detail="Tunnel not found")
    return tunnel


@router.delete("/api/tunnels/{tunnel_id}", status_code=204)
async def remove_tunnel(tunnel_id: str):
    tunnel = get_tunnel(tunnel_id)
    if not tunnel:
        raise HTTPException(status_code=404, detail="Tunnel not found")

    if tunnel.public_url:
        from ..main import remove_tunnel_origin
        remove_tunnel_origin(tunnel.public_url)

    await _tunnel_manager.stop_tunnel(tunnel_id)
    delete_tunnel(tunnel_id)

    await append_audit(AuditEntry(
        id=str(uuid.uuid4()),
        timestamp=time.time(),
        event_type="tunnel",
        metadata={"action": "delete", "tunnel_id": tunnel_id, "local_port": tunnel.local_port},
    ))


@router.post("/api/tunnels/{tunnel_id}/stop")
async def stop_tunnel_endpoint(tunnel_id: str):
    tunnel = get_tunnel(tunnel_id)
    if not tunnel:
        raise HTTPException(status_code=404, detail="Tunnel not found")

    if tunnel.public_url:
        from ..main import remove_tunnel_origin
        remove_tunnel_origin(tunnel.public_url)

    await _tunnel_manager.stop_tunnel(tunnel_id)
    tunnel.status = TunnelStatus.stopped
    tunnel.pid = None
    tunnel.public_url = None
    tunnel.started_at = None
    upsert_tunnel(tunnel)
    return tunnel


@router.post("/api/tunnels/{tunnel_id}/start")
async def start_tunnel_endpoint(tunnel_id: str):
    tunnel = get_tunnel(tunnel_id)
    if not tunnel:
        raise HTTPException(status_code=404, detail="Tunnel not found")

    if tunnel.status == TunnelStatus.running:
        raise HTTPException(status_code=409, detail="Tunnel is already running")

    for t in list_tunnels():
        if t.id != tunnel_id and t.local_port == tunnel.local_port and t.status in (TunnelStatus.running, TunnelStatus.starting):
            raise HTTPException(status_code=409, detail=f"Port {tunnel.local_port} is already tunneled by another tunnel")

    tunnel = await _tunnel_manager.start_tunnel(tunnel)

    if tunnel.public_url:
        from ..main import add_tunnel_origin
        add_tunnel_origin(tunnel.public_url)

    return tunnel
