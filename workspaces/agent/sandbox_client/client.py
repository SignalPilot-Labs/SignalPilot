"""SandboxClient — HTTP client for the Workspaces Sandbox server."""

import httpx

from .session import SessionHandler


class SandboxClient:
    """Async HTTP client for the sandbox server on :8080."""

    def __init__(self, base_url: str, secret: str) -> None:
        self._http = httpx.AsyncClient(
            base_url=base_url,
            timeout=httpx.Timeout(300),
            headers={"X-Internal-Secret": secret},
        )
        self.session = SessionHandler(self._http)

    async def health(self) -> dict:
        r = await self._http.get("/health")
        r.raise_for_status()
        return r.json()

    async def close(self) -> None:
        await self._http.aclose()
