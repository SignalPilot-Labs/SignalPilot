from __future__ import annotations

import os
from urllib.parse import quote, urlparse, urlunparse


def notebooks_base_url(request_base_url: str) -> str:
    base_url = (os.environ.get("SP_WEB_URL") or request_base_url).rstrip("/")
    parsed = urlparse(base_url)
    path = parsed.path.rstrip("/")
    if path.endswith("/notebooks"):
        path = f"{path.removesuffix('/notebooks')}/projects"
    elif not path.endswith("/projects"):
        path = f"{path}/projects" if path else "/projects"
    return urlunparse(
        parsed._replace(path=path, params="", query="", fragment="")
    ).rstrip("/")


def trail_url(
    file_key: str,
    session_id: str,
    request_base_url: str,
    *,
    project_id: str | None = None,
    branch: str | None = None,
) -> str:
    trail_base_url = notebooks_base_url(request_base_url)
    if project_id:
        url = f"{trail_base_url}?project={quote(project_id)}"
        if branch:
            url += f"&branch={quote(branch)}"
        return f"{url}&file={quote(file_key)}"
    return f"{trail_base_url}?file={quote(file_key)}&session_id={quote(session_id)}"
