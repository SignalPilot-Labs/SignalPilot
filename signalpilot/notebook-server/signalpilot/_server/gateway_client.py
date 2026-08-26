from __future__ import annotations

import os


def gateway_url() -> str:
    from signalpilot._utils.localhost import fix_localhost_url

    return fix_localhost_url(
        os.environ.get("SP_GATEWAY_URL", "http://localhost:3300")
    ).rstrip("/")


def gateway_headers() -> dict[str, str]:
    from signalpilot._server.auth.session_token import load_session_jwt

    jwt = load_session_jwt()
    if jwt:
        return {"Authorization": f"Bearer {jwt}"}
    api_key = os.environ.get("SP_API_KEY", "").strip()
    if api_key:
        if api_key.startswith("sp_"):
            return {"X-API-Key": api_key}
        return {"Authorization": f"Bearer {api_key}"}
    return {}
