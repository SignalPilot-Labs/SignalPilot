"""Read Tableau content: search, resolve refs, workbook details, downloads, renders.

A ``ref`` is either a Tableau LUID (uuid) or an exact content name. A name
that matches more than one item answers 409 with the candidate ids so the
agent can retry with an id.
"""

from __future__ import annotations

import csv
import io
import logging
import re
import zipfile
from typing import Any

from .client import LONG_TIMEOUT_S, TableauClient, TableauError
from .urls import content_browser_url

logger = logging.getLogger(__name__)

_LUID_RE = re.compile(r"^[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}$")
_MAX_SCAN = 5000
SEARCH_KINDS = ("workbook", "view", "datasource", "project")

# REST list endpoint, plural JSON key, singular JSON key.
_KIND_ENDPOINTS: dict[str, tuple[str, str, str]] = {
    "workbook": ("/workbooks", "workbooks", "workbook"),
    "view": ("/views", "views", "view"),
    "datasource": ("/datasources", "datasources", "datasource"),
    "project": ("/projects", "projects", "project"),
}


def is_luid(ref: str) -> bool:
    return bool(_LUID_RE.match((ref or "").strip()))


def _as_list(value: Any) -> list[dict[str, Any]]:
    if isinstance(value, list):
        return value
    if isinstance(value, dict):
        return [value]
    return []


async def list_paged(
    client: TableauClient,
    path: str,
    plural: str,
    single: str,
    *,
    params: dict[str, Any] | None = None,
    max_items: int = _MAX_SCAN,
) -> list[dict[str, Any]]:
    """Every item of a REST list endpoint, up to ``max_items``."""
    items: list[dict[str, Any]] = []
    page = 1
    page_size = max(1, min(max_items, 1000))
    while len(items) < max_items:
        data = await client.get_json(path, params={**(params or {}), "pageSize": page_size, "pageNumber": page})
        batch = _as_list((data.get(plural) or {}).get(single))
        items.extend(batch)
        total = int((data.get("pagination") or {}).get("totalAvailable") or 0)
        if not batch or len(items) >= total:
            break
        page += 1
    return items[:max_items]


def view_url(client: TableauClient, content_url: str) -> str | None:
    """Browser URL of a view from its REST contentUrl (``Workbook/sheets/View``)."""
    if not content_url:
        return None
    path = content_url.replace("/sheets/", "/")
    return content_browser_url(client.server, client.creds.site_content_url, f"views/{path}")


async def resolve(client: TableauClient, kind: str, ref: str) -> dict[str, Any]:
    """The REST object for ``ref`` (id or exact name). 404 when missing, 409 when ambiguous."""
    path, plural, single = _KIND_ENDPOINTS[kind]
    ref = (ref or "").strip()
    if not ref:
        raise TableauError(f"A {kind} id or name is required", status_code=400)
    if is_luid(ref):
        if kind in ("workbook", "datasource", "view"):
            data = await client.get_json(f"{path}/{ref}")
            item = data.get(single)
            if item:
                return item
            raise TableauError(f"Tableau {kind} {ref} not found", status_code=404)
        matches = [p for p in await list_paged(client, path, plural, single) if p.get("id") == ref]
    elif "," in ref:
        # Commas separate REST filter expressions, so scan and compare locally.
        matches = [p for p in await list_paged(client, path, plural, single) if p.get("name") == ref]
    else:
        matches = await list_paged(client, path, plural, single, params={"filter": f"name:eq:{ref}"}, max_items=50)
    if not matches and kind in ("datasource", "workbook") and "," not in ref:
        # Agents often pass the content_url that publish returned (for example
        # "SPdbt-fct_sales_lines") instead of the display name.
        matches = await list_paged(client, path, plural, single, params={"filter": f"contentUrl:eq:{ref}"}, max_items=50)
    if not matches:
        raise TableauError(f"No Tableau {kind} with the id, name, or content URL {ref!r}", status_code=404)
    if len(matches) > 1:
        options = ", ".join(
            f"{m.get('id')} (project {((m.get('project') or {}).get('name')) or '?'})" for m in matches[:10]
        )
        raise TableauError(f"{len(matches)} Tableau {kind}s are named {ref!r}; use an id: {options}", status_code=409)
    return matches[0]


# ── Search ──────────────────────────────────────────────────────────────────


def _hit(client: TableauClient, item: dict[str, Any]) -> dict[str, Any] | None:
    """Map one content-exploration search item to the runtime result shape."""
    c = item.get("content") or {}
    typ = c.get("type")
    site = client.creds.site_content_url
    base = {"updated_at": c.get("modifiedTime"), "content_url": c.get("repositoryUrl")}
    if typ == "workbook":
        return {
            "kind": "workbook",
            "id": c.get("luid"),
            "name": c.get("title"),
            "project": c.get("containerName"),
            "url": content_browser_url(client.server, site, f"workbooks/{c.get('id')}"),
            **base,
        }
    if typ == "view":
        return {
            "kind": "view",
            "id": c.get("luid"),
            "name": c.get("title"),
            "project": c.get("projectName") or c.get("locationName"),
            "url": content_browser_url(client.server, site, f"views/{c.get('path')}") if c.get("path") else None,
            "workbook": {"id": None, "name": c.get("containerName")},
            **base,
        }
    if typ in ("datasource", "unifieddatasource"):
        if typ == "unifieddatasource" and not c.get("datasourceIsPublished"):
            return None  # embedded in a workbook, not a published datasource
        return {
            "kind": "datasource",
            "id": c.get("datasourceLuid") or c.get("parentLuid") or c.get("luid"),
            "name": c.get("parentName") or c.get("title"),
            "project": c.get("containerName"),
            "url": content_browser_url(client.server, site, f"datasources/{c.get('id')}"),
            **base,
        }
    if typ == "project":
        return {
            "kind": "project",
            "id": c.get("luid"),
            "name": c.get("title"),
            "project": None,
            "url": content_browser_url(client.server, site, f"projects/{c.get('id')}"),
            **base,
        }
    return None


async def _fill_view_workbook_ids(client: TableauClient, results: list[dict[str, Any]]) -> None:
    """Search hits for views carry only the workbook name; look up the workbook ids."""
    wanted = {
        (r.get("content_url") or "").split("/")[0] for r in results if r["kind"] == "view" and r.get("content_url")
    }
    ids: dict[str, str] = {}
    for content_url in list(wanted)[:10]:
        try:
            found = await list_paged(
                client,
                "/workbooks",
                "workbooks",
                "workbook",
                params={"filter": f"contentUrl:eq:{content_url}"},
                max_items=1,
            )
        except TableauError:
            continue
        if found:
            ids[content_url] = found[0].get("id")
    for r in results:
        if r["kind"] == "view" and r.get("content_url"):
            r["workbook"]["id"] = ids.get(r["content_url"].split("/")[0])


def _rest_hit(client: TableauClient, kind: str, obj: dict[str, Any]) -> dict[str, Any]:
    hit: dict[str, Any] = {
        "kind": kind,
        "id": obj.get("id"),
        "name": obj.get("name"),
        "project": (obj.get("project") or {}).get("name"),
        "url": obj.get("webpageUrl"),
        "updated_at": obj.get("updatedAt"),
        "content_url": obj.get("contentUrl"),
    }
    if kind == "view":
        hit["url"] = view_url(client, obj.get("contentUrl") or "")
        wb = obj.get("workbook") or {}
        hit["workbook"] = {"id": wb.get("id"), "name": wb.get("name")}
    if kind == "project":
        hit["project"] = None
    return hit


async def _search_rest(client: TableauClient, q: str, kinds: list[str], limit: int) -> list[dict[str, Any]]:
    """Fallback search: list each kind and match the name locally (case-insensitive)."""
    needle = q.casefold()
    results: list[dict[str, Any]] = []
    for kind in kinds:
        path, plural, single = _KIND_ENDPOINTS[kind]
        params: dict[str, Any] = {}
        if kind == "view":
            params["fields"] = "_default_,workbook.name,project.name"
        if kind != "project":
            params["sort"] = "updatedAt:desc"
        for obj in await list_paged(client, path, plural, single, params=params, max_items=1000):
            if needle in str(obj.get("name") or "").casefold():
                results.append(_rest_hit(client, kind, obj))
    return results[:limit]


async def search(client: TableauClient, q: str, kind: str = "all", limit: int = 25) -> list[dict[str, Any]]:
    """Find workbooks, views, published datasources, and projects by name."""
    kinds = list(SEARCH_KINDS) if kind == "all" else [kind]
    limit = max(1, min(limit, 100))
    q = (q or "").strip()
    if q:
        params: dict[str, Any] = {"terms": q, "limit": min(100, limit * 2)}
        if kind != "all":
            params["filter"] = f"type:eq:{kind}"
        try:
            data = await client.get_json("/api/-/search", scope="root", params=params)
            items = ((data.get("hits") or {}).get("items")) or []
            results = [h for h in (_hit(client, i) for i in items) if h and h["kind"] in kinds][:limit]
            await _fill_view_workbook_ids(client, results)
            return results
        except TableauError as exc:
            logger.info("tableau content search unavailable (%s); using REST list fallback", exc.message)
    return await _search_rest(client, q, kinds, limit)


# ── Workbooks ───────────────────────────────────────────────────────────────


async def workbook_views(client: TableauClient, workbook_id: str) -> list[dict[str, Any]]:
    data = await client.get_json(f"/workbooks/{workbook_id}/views")
    out = []
    for v in _as_list((data.get("views") or {}).get("view")):
        entry: dict[str, Any] = {
            "id": v.get("id"),
            "name": v.get("name"),
            "url": view_url(client, v.get("contentUrl") or ""),
        }
        if v.get("sheetType"):
            entry["sheet_type"] = v.get("sheetType")
        out.append(entry)
    return out


async def workbook_connections_raw(client: TableauClient, workbook_id: str) -> list[dict[str, Any]]:
    data = await client.get_json(f"/workbooks/{workbook_id}/connections")
    return _as_list((data.get("connections") or {}).get("connection"))


def connection_summary(conn: dict[str, Any]) -> dict[str, Any]:
    return {
        "id": conn.get("id"),
        "type": conn.get("type"),
        "server_address": conn.get("serverAddress") or "",
        "server_port": conn.get("serverPort") or None,
        "user_name": conn.get("userName"),
        "embed_password": bool(conn.get("embedPassword")),
        "datasource_name": (conn.get("datasource") or {}).get("name"),
    }


def workbook_url(workbook: dict[str, Any]) -> str | None:
    return workbook.get("webpageUrl")


async def workbook_details(client: TableauClient, ref: str) -> dict[str, Any]:
    wb = await resolve(client, "workbook", ref)
    project = wb.get("project") or {}
    return {
        "id": wb.get("id"),
        "name": wb.get("name"),
        "project": {"id": project.get("id"), "name": project.get("name")},
        "url": workbook_url(wb),
        "updated_at": wb.get("updatedAt"),
        "views": await workbook_views(client, wb["id"]),
        "connections": [connection_summary(c) for c in await workbook_connections_raw(client, wb["id"])],
    }


def extract_twb(data: bytes) -> bytes:
    """The ``.twb`` XML inside a ``.twbx`` zip; plain ``.twb`` bytes pass through."""
    if not data.startswith(b"PK"):
        return data
    try:
        with zipfile.ZipFile(io.BytesIO(data)) as zf:
            names = [n for n in zf.namelist() if n.lower().endswith(".twb")]
            if not names:
                raise TableauError("The packaged workbook contains no .twb file", status_code=502)
            names.sort(key=lambda n: (n.count("/"), len(n)))  # prefer the root-level workbook
            return zf.read(names[0])
    except zipfile.BadZipFile:
        raise TableauError("Tableau returned a corrupt packaged workbook", status_code=502) from None


async def download_workbook(client: TableauClient, ref: str) -> tuple[dict[str, Any], bytes]:
    """(workbook REST object, .twb bytes). Extracts are never downloaded."""
    wb = await resolve(client, "workbook", ref)
    resp = await client.request(
        "GET",
        f"/workbooks/{wb['id']}/content",
        params={"includeExtract": "false"},
        accept="*/*",
        timeout=LONG_TIMEOUT_S,
    )
    return wb, extract_twb(resp.content)


# ── Views ───────────────────────────────────────────────────────────────────


async def view_image(
    client: TableauClient, ref: str, *, width: int | None = None, height: int | None = None, max_age: int = 1
) -> tuple[dict[str, Any], bytes]:
    view = await resolve(client, "view", ref)
    params: dict[str, Any] = {"resolution": "high", "maxAge": max(1, max_age)}
    if width:
        params["vizWidth"] = width
    if height:
        params["vizHeight"] = height
    resp = await client.request(
        "GET", f"/views/{view['id']}/image", params=params, accept="*/*", timeout=LONG_TIMEOUT_S
    )
    return view, resp.content


def truncate_csv(text: str, max_rows: int) -> str:
    """Keep the header plus ``max_rows`` data rows (quoted newlines stay intact)."""
    reader = csv.reader(io.StringIO(text))
    out = io.StringIO()
    writer = csv.writer(out, lineterminator="\n")
    for index, row in enumerate(reader):
        if index > max_rows:
            break
        writer.writerow(row)
    return out.getvalue()


async def view_data(client: TableauClient, ref: str, *, max_rows: int = 200) -> tuple[dict[str, Any], str]:
    view = await resolve(client, "view", ref)
    resp = await client.request(
        "GET", f"/views/{view['id']}/data", params={"maxAge": 1}, accept="*/*", timeout=LONG_TIMEOUT_S
    )
    text = resp.content.decode("utf-8-sig", errors="replace")
    return view, truncate_csv(text, max(1, max_rows))


# ── Projects ────────────────────────────────────────────────────────────────


async def list_projects(client: TableauClient) -> list[dict[str, Any]]:
    return [
        {"id": p.get("id"), "name": p.get("name"), "parent_id": p.get("parentProjectId")}
        for p in await list_paged(client, "/projects", "projects", "project")
    ]


async def resolve_project(client: TableauClient, ref: str | None) -> dict[str, Any]:
    """Project by id or name; the site default project when ``ref`` is empty."""
    projects = await list_projects(client)
    if not projects:
        raise TableauError("The Tableau site has no projects", status_code=404)
    ref = (ref or "").strip()
    if not ref:
        top = [p for p in projects if not p["parent_id"]]
        default = next((p for p in top if str(p["name"]).casefold() == "default"), None)
        return default or (top or projects)[0]
    if is_luid(ref):
        match = next((p for p in projects if p["id"] == ref), None)
        if match:
            return match
        raise TableauError(f"Tableau project {ref} not found", status_code=404)
    exact = [p for p in projects if p["name"] == ref] or [
        p for p in projects if str(p["name"]).casefold() == ref.casefold()
    ]
    if not exact:
        raise TableauError(f"No Tableau project named {ref!r}", status_code=404)
    top = [p for p in exact if not p["parent_id"]]
    if len(exact) > 1 and len(top) != 1:
        raise TableauError(f"{len(exact)} Tableau projects are named {ref!r}; use an id", status_code=409)
    return top[0] if len(exact) > 1 else exact[0]
