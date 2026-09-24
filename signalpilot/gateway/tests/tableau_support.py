"""Shared fake Tableau server for the Tableau client and API tests."""

from __future__ import annotations

import json
from collections.abc import Callable
from typing import Any

import httpx

from gateway.tableau.client import TableauClient, TableauCredentials

SERVER = "https://tab.example.com"
SITE_ID = "site-luid"
PAT_SECRET = "pat-secret-value"
CREDS = TableauCredentials(SERVER, "mysite", "pat", PAT_SECRET)


class FakeTableau:
    """A tiny Tableau: records requests, issues tokens, routes by (method, path)."""

    def __init__(self) -> None:
        self.requests: list[httpx.Request] = []
        self.signins = 0
        self.valid_tokens: set[str] = set()
        self.routes: dict[tuple[str, str], Callable[[httpx.Request], httpx.Response]] = {}

    def sign_in(self) -> str:
        self.signins += 1
        token = f"tok-{self.signins}"
        self.valid_tokens = {token}  # a PAT has one session: the new token replaces the old
        return token

    def handler(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        path = request.url.path
        if path.endswith("/serverinfo"):
            return httpx.Response(200, json={"serverInfo": {"restApiVersion": "3.31"}})
        if path.endswith("/auth/signin"):
            body = json.loads(request.content)
            if body["credentials"]["personalAccessTokenSecret"] != PAT_SECRET:
                return httpx.Response(
                    401, json={"error": {"summary": "Signin Error", "detail": "bad PAT", "code": "401001"}}
                )
            return httpx.Response(
                200,
                json={
                    "credentials": {
                        "token": self.sign_in(),
                        "site": {"id": SITE_ID, "contentUrl": "mysite"},
                        "user": {"id": "user-1"},
                    }
                },
            )
        if request.headers.get("X-Tableau-Auth") not in self.valid_tokens:
            return httpx.Response(401, json={"error": {"summary": "Unauthorized", "detail": "token", "code": "401002"}})
        route = self.routes.get((request.method, path))
        if route is None:
            return httpx.Response(404, json={"error": {"summary": "Not Found", "detail": path, "code": "404000"}})
        return route(request)

    def client(self) -> TableauClient:
        return TableauClient(CREDS, cache_key="org-1", transport=httpx.MockTransport(self.handler))


def _json(data: dict[str, Any]) -> Callable[[httpx.Request], httpx.Response]:
    return lambda _req: httpx.Response(200, json=data)
