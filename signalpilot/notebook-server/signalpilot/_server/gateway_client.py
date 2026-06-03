from __future__ import annotations

import os


def gateway_url() -> str:
    from signalpilot._utils.localhost import fix_localhost_url

    return fix_localhost_url(
        os.environ.get("SP_GATEWAY_URL", "http://localhost:3300")
    ).rstrip("/")


def gateway_headers() -> dict[str, str]:
    jwt = os.environ.get("SP_SESSION_JWT", "")
    if jwt:
        return {"Authorization": f"Bearer {jwt}"}
    api_key = os.environ.get("SP_API_KEY", "")
    if api_key:
        return {"X-API-Key": api_key}
    return {}
