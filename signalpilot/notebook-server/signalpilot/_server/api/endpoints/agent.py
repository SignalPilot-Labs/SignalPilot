"""REST API endpoints for agent management.

These endpoints do NOT require a notebook session — they work
independently for SDK and API access.
"""

from __future__ import annotations

import json
from collections.abc import AsyncGenerator
from typing import TYPE_CHECKING

import msgspec
from starlette.responses import Response, StreamingResponse

from signalpilot import _loggers
from signalpilot._server.router import APIRouter

if TYPE_CHECKING:
    from starlette.requests import Request

LOGGER = _loggers.sp_logger()

router = APIRouter()


class CreateAgentRequest(msgspec.Struct, rename="camel"):
    model: str = "claude-sonnet-4-20250514"
    system_prompt: str | None = None
    session_id: str | None = None


class AgentMessageRequest(msgspec.Struct, rename="camel"):
    instance_id: str
    message: str
    new_chat: bool = False
    message_history: list[dict[str, str]] = msgspec.field(default_factory=list)
    context_file: str | None = None


class AgentStopRequest(msgspec.Struct, rename="camel"):
    instance_id: str


class AgentStatusRequest(msgspec.Struct, rename="camel"):
    instance_id: str


class AgentListRequest(msgspec.Struct, rename="camel"):
    session_id: str | None = None


class AgentEventsRequest(msgspec.Struct, rename="camel"):
    instance_id: str
    after_index: int = -1


@router.get("/auth-status")
async def agent_auth_status(*, request: Request) -> Response:
    """Check if AI credentials are configured."""
    import os
    has_oauth = bool(os.environ.get("CLAUDE_CODE_OAUTH_TOKEN") or os.environ.get("OAUTH_TOKEN"))
    has_api_key = bool(os.environ.get("ANTHROPIC_API_KEY"))

    # Also check gateway user secrets
    has_gateway_key = False
    try:
        from signalpilot._server.files.project_sync import _gateway_url, _gateway_headers
        import httpx
        resp = httpx.get(
            f"{_gateway_url()}/api/user/secrets",
            headers=_gateway_headers(),
            timeout=5.0,
        )
        if resp.status_code == 200:
            has_gateway_key = resp.json().get("has_anthropic_key", False)
    except Exception:
        pass

    configured = has_oauth or has_api_key or has_gateway_key
    method = "oauth" if has_oauth else ("api_key" if has_api_key else ("gateway" if has_gateway_key else "none"))

    return Response(
        content=json.dumps({
            "configured": configured,
            "method": method,
        }),
        media_type="application/json",
    )


@router.post("/save-api-key")
async def save_api_key(*, request: Request) -> Response:
    """Save Anthropic API key to gateway user secrets."""
    body = await request.json()
    api_key = body.get("api_key", "").strip()
    if not api_key:
        return Response(
            content=json.dumps({"error": "API key required"}),
            media_type="application/json",
            status_code=400,
        )

    import os
    try:
        from signalpilot._server.files.project_sync import _gateway_url, _gateway_headers
        import httpx
        resp = httpx.put(
            f"{_gateway_url()}/api/user/secrets",
            headers={**_gateway_headers(), "Content-Type": "application/json"},
            json={"anthropic_api_key": api_key},
            timeout=10.0,
        )
        if resp.status_code == 200:
            # Also set it locally for immediate use
            os.environ["ANTHROPIC_API_KEY"] = api_key
            return Response(
                content=json.dumps({"success": True}),
                media_type="application/json",
            )
        return Response(
            content=json.dumps({"error": f"Gateway error: {resp.status_code}"}),
            media_type="application/json",
            status_code=500,
        )
    except Exception as e:
        # Fallback: just set locally
        os.environ["ANTHROPIC_API_KEY"] = api_key
        return Response(
            content=json.dumps({"success": True, "local_only": True}),
            media_type="application/json",
        )


@router.post("/create")
async def create_agent(*, request: Request) -> Response:
    """Create a new agent instance."""
    from signalpilot._server.ai.agent_manager import get_agent_manager
    from signalpilot._server.api.utils import parse_request

    body = await parse_request(request, cls=CreateAgentRequest)
    manager = get_agent_manager()

    instance = manager.create_instance(
        session_id=body.session_id,
        model=body.model,
        system_prompt=body.system_prompt,
    )

    return Response(
        content=json.dumps({
            "instanceId": instance.id,
            "sessionId": instance.session_id,
            "status": instance.status,
            "model": instance.model,
        }),
        media_type="application/json",
    )


@router.post("/message")
async def send_agent_message(*, request: Request) -> StreamingResponse:
    """Send a message to an agent instance. Returns SSE stream."""
    from signalpilot._server.ai.agent_manager import get_agent_manager
    from signalpilot._server.api.utils import parse_request

    body = await parse_request(request, cls=AgentMessageRequest)
    manager = get_agent_manager()

    async def event_stream() -> AsyncGenerator[str, None]:
        try:
            idx = 0
            # Resolve cloud project cwd if applicable
            agent_cwd = None
            project_id = request.headers.get("x-gateway-project-id")
            if project_id:
                branch = request.headers.get("x-gateway-branch-id", "main")
                from signalpilot._server.files.project_sync import local_project_dir
                local_dir = local_project_dir(project_id, branch)
                if local_dir.exists():
                    agent_cwd = str(local_dir)

            async for event in manager.send_message(
                instance_id=body.instance_id,
                message=body.message,
                new_chat=body.new_chat,
                message_history=body.message_history if body.message_history else None,
                app=request.app,
                context_file=body.context_file,
                cwd=agent_cwd,
            ):
                data = json.dumps({
                    "type": event.type,
                    "content": event.content,
                    "tool_name": event.tool_name,
                    "tool_input": event.tool_input,
                    "tool_call_id": event.tool_call_id,
                    "is_error": event.is_error,
                    "cost_usd": event.cost_usd,
                    "turn": event.turn,
                    "idx": idx,
                }, default=str)
                yield f"data: {data}\n\n"
                idx += 1
        except Exception as e:
            LOGGER.error(f"Error in agent message stream: {e}")
            yield f"data: {json.dumps({'type': 'error', 'content': str(e), 'is_error': True})}\n\n"

    return StreamingResponse(
        event_stream(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


@router.post("/stop")
async def stop_agent_instance(*, request: Request) -> Response:
    """Stop a running agent instance."""
    from signalpilot._server.ai.agent_manager import get_agent_manager
    from signalpilot._server.api.utils import parse_request

    body = await parse_request(request, cls=AgentStopRequest)
    manager = get_agent_manager()

    instance = manager.get_instance(body.instance_id)
    if not instance:
        return Response(
            content=json.dumps({"error": "Instance not found"}),
            media_type="application/json",
            status_code=404,
        )

    success = manager.stop_instance(body.instance_id)
    return Response(
        content=json.dumps({"success": success}),
        media_type="application/json",
    )


@router.post("/status")
async def get_agent_status(*, request: Request) -> Response:
    """Get agent instance status."""
    from signalpilot._server.ai.agent_manager import get_agent_manager
    from signalpilot._server.api.utils import parse_request

    body = await parse_request(request, cls=AgentStatusRequest)
    manager = get_agent_manager()

    instance = manager.get_instance(body.instance_id)
    if not instance:
        return Response(
            content=json.dumps({"error": "Instance not found"}),
            media_type="application/json",
            status_code=404,
        )

    return Response(
        content=json.dumps({
            "instanceId": instance.id,
            "sessionId": instance.session_id,
            "status": instance.status,
            "model": instance.model,
            "messageCount": instance.message_count,
            "createdAt": instance.created_at,
            "lastError": instance.last_error,
            "eventCount": len(instance.event_buffer),
        }),
        media_type="application/json",
    )


@router.post("/list")
async def list_agents(*, request: Request) -> Response:
    """List all agent instances."""
    from signalpilot._server.ai.agent_manager import get_agent_manager
    from signalpilot._server.api.utils import parse_request

    body = await parse_request(request, cls=AgentListRequest)
    manager = get_agent_manager()
    session_id = body.session_id

    instances = manager.list_instances(session_id)
    return Response(
        content=json.dumps({
            "instances": [
                {
                    "instanceId": i.id,
                    "sessionId": i.session_id,
                    "status": i.status,
                    "model": i.model,
                    "messageCount": i.message_count,
                    "createdAt": i.created_at,
                }
                for i in instances
            ]
        }),
        media_type="application/json",
    )


@router.post("/events")
async def get_agent_events(*, request: Request) -> Response:
    """Get buffered events for catch-up."""
    from signalpilot._server.ai.agent_manager import get_agent_manager
    from signalpilot._server.api.utils import parse_request

    body = await parse_request(request, cls=AgentEventsRequest)
    manager = get_agent_manager()

    events = manager.get_events(body.instance_id, body.after_index)
    return Response(
        content=json.dumps({"events": events, "count": len(events)}),
        media_type="application/json",
    )
