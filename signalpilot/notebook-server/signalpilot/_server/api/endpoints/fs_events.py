from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING

from starlette.authentication import requires
from starlette.responses import Response, StreamingResponse

from signalpilot._server.api.deps import AppState
from signalpilot._server.files.fs_event_stream import (
    FileSystemEventBroker,
    fs_event_generator,
)
from signalpilot._server.router import APIRouter

if TYPE_CHECKING:
    from starlette.requests import Request

router = APIRouter()


@router.get("/events")
@requires("edit")
async def file_system_events(*, request: Request) -> Response:
    app_state = AppState.from_request(request)
    directory = app_state.session_manager.workspace.directory

    # 204 is chosen specifically to suppress EventSource auto-retry in the browser.
    if directory is None:
        return Response(status_code=204)

    root = Path(directory)
    broker = FileSystemEventBroker.for_root(root)
    broker.start()

    return StreamingResponse(
        fs_event_generator(broker),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )
