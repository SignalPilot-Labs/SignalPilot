"""Publish workbooks and datasources to Tableau with SignalPilot credentials.

Workbook recipe (verified on Tableau Cloud): the publish-time credential
mapping does not apply to embedded SQL Server connections and the connection
check then fails (403132). So publish with ``skipConnectionCheck=true``, then
``PUT /workbooks/{id}/connections/{cid}`` with userName/password/embedPassword
for each connection on the SignalPilot connection's host.

Datasource recipe: a live .tds (see ``connections.build_tds``) published with
``<connectionCredentials embed='true'/>`` in the request payload.
"""

from __future__ import annotations

import logging
import uuid
from typing import Any
from xml.sax.saxutils import quoteattr

from .client import LONG_TIMEOUT_S, TableauClient, TableauError
from .connections import ConnectionTarget, build_tds
from .content import resolve_project, workbook_connections_raw, workbook_views
from .site_refs import normalize_workbook_bytes

logger = logging.getLogger(__name__)

MAX_SINGLE_PUBLISH_BYTES = 64 * 1024 * 1024
# Connections that point at other Tableau content, not at a database.
_NON_DB_TYPES = frozenset({"sqlproxy"})


def multipart(payload_xml: str, part_name: str, filename: str, content: bytes) -> tuple[str, bytes]:
    """(content type, body) of a Tableau ``multipart/mixed`` publish request."""
    boundary = uuid.uuid4().hex
    head = (
        f'--{boundary}\r\nContent-Disposition: name="request_payload"\r\nContent-Type: text/xml\r\n\r\n'
        f'{payload_xml}\r\n--{boundary}\r\nContent-Disposition: name="{part_name}"; filename="{filename}"\r\n'
        "Content-Type: application/octet-stream\r\n\r\n"
    ).encode()
    return f"multipart/mixed; boundary={boundary}", head + content + f"\r\n--{boundary}--\r\n".encode()


def _credentials_xml(target: ConnectionTarget) -> str:
    return (
        f"<connectionCredentials name={quoteattr(target.username)} "
        f"password={quoteattr(target.password)} embed='true' />"
    )


async def _embed_credentials(
    client: TableauClient, workbook_id: str, target: ConnectionTarget | None
) -> tuple[list[str], list[dict[str, Any]]]:
    """PUT credentials on every connection on the target host; report the rest."""
    embedded: list[str] = []
    unbound: list[dict[str, Any]] = []
    for conn in await workbook_connections_raw(client, workbook_id):
        conn_type = conn.get("type") or ""
        if conn_type in _NON_DB_TYPES:
            continue
        address = conn.get("serverAddress") or ""
        ds_name = (conn.get("datasource") or {}).get("name")
        entry = {"type": conn_type, "server_address": address, "datasource_name": ds_name}
        if target is None or not target.password or not target.matches_host(address):
            unbound.append(entry)
            continue
        try:
            await client.request(
                "PUT",
                f"/workbooks/{workbook_id}/connections/{conn.get('id')}",
                json={
                    "connection": {
                        "serverAddress": address,
                        "userName": target.username,
                        "password": target.password,
                        "embedPassword": True,
                    }
                },
                headers={"Content-Type": "application/json"},
            )
        except TableauError as exc:
            unbound.append({**entry, "error": exc.message})
            continue
        embedded.append(ds_name or address)
    return embedded, unbound


async def publish_workbook(
    client: TableauClient,
    *,
    data: bytes,
    name: str,
    project: str | None = None,
    overwrite: bool = True,
    show_tabs: bool = True,
    description: str | None = None,
    target: ConnectionTarget | None = None,
) -> dict[str, Any]:
    """Publish a .twb or .twbx, then bind SignalPilot credentials to matching connections."""
    if not data:
        raise TableauError("The workbook file is empty", status_code=400)
    if len(data) > MAX_SINGLE_PUBLISH_BYTES:
        raise TableauError("Workbooks over 64 MB are not supported yet", status_code=413)
    if not (name or "").strip():
        raise TableauError("A workbook name is required", status_code=400)
    workbook_type = "twbx" if data.startswith(b"PK") else "twb"
    # Published datasources must live on this site: point sqlproxy references at it.
    data, site_refs = normalize_workbook_bytes(data, client.server, client.creds.site_content_url)
    proj = await resolve_project(client, project)
    attrs = f"name={quoteattr(name.strip())} showTabs='{'true' if show_tabs else 'false'}'"
    if description:
        attrs += f" description={quoteattr(description)}"
    payload = f"<tsRequest><workbook {attrs}><project id={quoteattr(proj['id'])} /></workbook></tsRequest>"
    content_type, body = multipart(payload, "tableau_workbook", f"workbook.{workbook_type}", data)
    resp = await client.request(
        "POST",
        "/workbooks",
        params={
            "overwrite": "true" if overwrite else "false",
            "workbookType": workbook_type,
            "skipConnectionCheck": "true",
        },
        content=body,
        headers={"Content-Type": content_type},
        timeout=LONG_TIMEOUT_S,
    )
    wb = (resp.json() or {}).get("workbook") or {}
    if not wb.get("id"):
        raise TableauError("Tableau accepted the workbook but returned no id")
    embedded, unbound = await _embed_credentials(client, wb["id"], target)
    logger.info("tableau.publish_workbook workbook=%s embedded=%d unbound=%d", wb["id"], len(embedded), len(unbound))
    return {
        "id": wb["id"],
        "name": wb.get("name"),
        "url": wb.get("webpageUrl"),
        "project": {"id": proj["id"], "name": proj["name"]},
        "views": await workbook_views(client, wb["id"]),
        "credentials_embedded": embedded,
        "unbound_connections": unbound,
        "site_references_rewritten": site_refs,
    }


async def publish_datasource(
    client: TableauClient,
    *,
    target: ConnectionTarget,
    name: str,
    database: str | None = None,
    schema: str | None = None,
    table: str | None = None,
    sql: str | None = None,
    project: str | None = None,
    overwrite: bool = True,
    description: str | None = None,
) -> dict[str, Any]:
    """Publish a live datasource on one table or SQL query of ``target``, credentials embedded."""
    if not (name or "").strip():
        raise TableauError("A datasource name is required", status_code=400)
    tds = build_tds(target, caption=name.strip(), database=database, schema=schema, table=table, sql=sql)
    proj = await resolve_project(client, project)
    attrs = f"name={quoteattr(name.strip())}"
    if description:
        attrs += f" description={quoteattr(description)}"
    payload = (
        f"<tsRequest><datasource {attrs}>{_credentials_xml(target)}"
        f"<project id={quoteattr(proj['id'])} /></datasource></tsRequest>"
    )
    content_type, body = multipart(payload, "tableau_datasource", "datasource.tds", tds.encode("utf-8"))
    resp = await client.request(
        "POST",
        "/datasources",
        params={"overwrite": "true" if overwrite else "false", "datasourceType": "tds"},
        content=body,
        headers={"Content-Type": content_type},
        timeout=LONG_TIMEOUT_S,
    )
    ds = (resp.json() or {}).get("datasource") or {}
    logger.info("tableau.publish_datasource datasource=%s class=%s", ds.get("id"), target.tableau_class)
    return {
        "id": ds.get("id"),
        "name": ds.get("name"),
        "content_url": ds.get("contentUrl"),
        "project": {"id": proj["id"], "name": proj["name"]},
        "url": ds.get("webpageUrl"),
    }
