"""SessionHandler — Claude SDK session lifecycle over HTTP."""

import json
import logging
from collections.abc import AsyncIterator

import httpx

log = logging.getLogger("sandbox_client.session")


class SessionHandler:
    """Handler for sandbox /session/* HTTP endpoints."""

    def __init__(self, http: httpx.AsyncClient) -> None:
        self._http = http

    async def start(self, options: dict) -> str:
        resp = await self._http.post("/session/start", json=options)
        resp.raise_for_status()
        return resp.json()["session_id"]

    async def stream_events(self, session_id: str) -> AsyncIterator[dict]:
        async with self._http.stream(
            "GET", f"/session/{session_id}/events", timeout=None,
        ) as resp:
            resp.raise_for_status()
            buffer = ""
            async for chunk in resp.aiter_text():
                buffer += chunk
                while "\n\n" in buffer:
                    event_str, buffer = buffer.split("\n\n", 1)
                    event = _parse_sse_event(event_str)
                    if event:
                        yield event

    async def send_message(self, session_id: str, text: str) -> None:
        resp = await self._http.post(
            f"/session/{session_id}/message", json={"text": text},
        )
        resp.raise_for_status()

    async def interrupt(self, session_id: str) -> None:
        resp = await self._http.post(f"/session/{session_id}/interrupt")
        resp.raise_for_status()

    async def stop(self, session_id: str) -> None:
        resp = await self._http.post(f"/session/{session_id}/stop")
        resp.raise_for_status()


def _parse_sse_event(raw: str) -> dict | None:
    event_type = "message"
    data_lines: list[str] = []

    for line in raw.strip().split("\n"):
        if line.startswith("event:"):
            event_type = line[6:].strip()
        elif line.startswith("data:"):
            data_lines.append(line[5:].strip())

    if not data_lines:
        return None

    data_str = "\n".join(data_lines)
    try:
        data = json.loads(data_str)
    except json.JSONDecodeError:
        log.warning("Malformed SSE JSON: %s", data_str[:200])
        data = {"raw": data_str}

    return {"event": event_type, "data": data}
