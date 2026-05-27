# Copyright 2026 SignalPilot. All rights reserved.
from __future__ import annotations

import urllib.request
import urllib.error
import json
from typing import Any


class GatewayClient:
    """Synchronous HTTP client for SignalPilot Gateway REST API."""

    def __init__(self, base_url: str, api_key: str = "", session_jwt: str = "") -> None:
        from signalpilot._utils.localhost import fix_localhost_url
        self.base_url = fix_localhost_url(base_url).rstrip("/")
        self.api_key = api_key
        self.session_jwt = session_jwt

    def _headers(self) -> dict[str, str]:
        hdrs: dict[str, str] = {
            "Content-Type": "application/json",
            "Accept": "application/json",
        }
        if self.session_jwt:
            hdrs["Authorization"] = f"Bearer {self.session_jwt}"
        elif self.api_key:
            hdrs["X-API-Key"] = self.api_key
        return hdrs

    def _get(self, path: str, params: dict[str, str] | None = None) -> Any:
        url = f"{self.base_url}{path}"
        if params:
            qs = "&".join(f"{k}={v}" for k, v in params.items() if v is not None)
            if qs:
                url = f"{url}?{qs}"
        req = urllib.request.Request(url, headers=self._headers(), method="GET")
        try:
            with urllib.request.urlopen(req, timeout=30) as resp:
                return json.loads(resp.read().decode())
        except urllib.error.HTTPError as e:
            body = e.read().decode() if e.fp else ""
            raise GatewayError(e.code, body) from e
        except urllib.error.URLError as e:
            raise GatewayUnavailable(str(e.reason)) from e

    def _post(self, path: str, body: dict[str, Any]) -> Any:
        url = f"{self.base_url}{path}"
        data = json.dumps(body).encode()
        req = urllib.request.Request(
            url, data=data, headers=self._headers(), method="POST"
        )
        try:
            with urllib.request.urlopen(req, timeout=60) as resp:
                return json.loads(resp.read().decode())
        except urllib.error.HTTPError as e:
            resp_body = e.read().decode() if e.fp else ""
            raise GatewayError(e.code, resp_body) from e
        except urllib.error.URLError as e:
            raise GatewayUnavailable(str(e.reason)) from e

    def list_connections(self) -> list[dict[str, Any]]:
        """GET /api/connections — list all configured database connections."""
        return self._get("/api/connections")

    def get_schema(
        self, connection_name: str, compact: bool = False
    ) -> dict[str, Any]:
        """GET /api/connections/{name}/schema — full schema with columns."""
        params = {"compact": "true" if compact else "false"}
        return self._get(f"/api/connections/{connection_name}/schema", params)

    def explore_table(
        self, connection_name: str, table: str
    ) -> dict[str, Any]:
        """GET /api/connections/{name}/schema/explore-table — deep table info."""
        return self._get(
            f"/api/connections/{connection_name}/schema/explore-table",
            {"table": table},
        )

    def execute_query(
        self,
        connection_name: str,
        sql: str,
        row_limit: int = 1000,
        timeout_seconds: int = 30,
    ) -> dict[str, Any]:
        """POST /api/query — execute governed SQL query."""
        return self._post(
            "/api/query",
            {
                "connection_name": connection_name,
                "sql": sql,
                "row_limit": row_limit,
                "timeout_seconds": timeout_seconds,
            },
        )

    def explain_query(
        self, connection_name: str, sql: str
    ) -> dict[str, Any]:
        """POST /api/query/explain — query plan without execution."""
        return self._post(
            "/api/query/explain",
            {"connection_name": connection_name, "sql": sql},
        )

    def is_available(self) -> bool:
        """Check if the gateway is reachable."""
        try:
            self._get("/health")
            return True
        except Exception:
            return False


class GatewayError(Exception):
    """HTTP error from the gateway."""

    def __init__(self, status_code: int, body: str) -> None:
        self.status_code = status_code
        self.body = body
        super().__init__(f"Gateway returned {status_code}: {body}")


class GatewayUnavailable(Exception):
    """Gateway is not reachable."""
