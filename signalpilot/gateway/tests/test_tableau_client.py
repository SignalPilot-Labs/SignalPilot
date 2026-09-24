"""Tableau client against httpx.MockTransport: token caching, 401 retry, publish binding, search."""

from __future__ import annotations

import json
from typing import Any

import httpx
import pytest

from gateway.tableau import content, publish, vds
from gateway.tableau.client import TableauClient, TableauCredentials, TableauError, clear_token_cache
from gateway.tableau.connections import ConnectionTarget

from .tableau_support import SERVER, SITE_ID, FakeTableau, _json


@pytest.fixture(autouse=True)
def _fresh_cache():
    clear_token_cache()
    yield
    clear_token_cache()


async def test_sign_in_is_cached_across_clients_and_version_is_capped() -> None:
    fake = FakeTableau()
    fake.routes[("GET", f"/api/3.29/sites/{SITE_ID}/users/user-1")] = _json(
        {"user": {"name": "a@b.c", "siteRole": "Creator"}}
    )
    async with fake.client() as client:
        user = await client.current_user()
        await client.current_user()
    async with fake.client() as client:
        await client.current_user()
    assert user["siteRole"] == "Creator"
    assert fake.signins == 1  # never one sign-in per call
    assert all("/api/3.29/" in str(r.url) for r in fake.requests if "serverinfo" not in str(r.url))


async def test_401_signs_in_again_once() -> None:
    fake = FakeTableau()
    fake.routes[("GET", f"/api/3.29/sites/{SITE_ID}/projects")] = _json(
        {"pagination": {"totalAvailable": "1"}, "projects": {"project": [{"id": "p1", "name": "default"}]}}
    )
    async with fake.client() as client:
        await content.list_projects(client)
        fake.sign_in()  # another process used the PAT: our token is now invalid
        projects = await content.list_projects(client)
    assert projects == [{"id": "p1", "name": "default", "parent_id": None}]
    assert fake.signins == 3  # ours, the other process's, and exactly one re-sign-in


async def test_persistent_401_raises_after_one_retry() -> None:
    fake = FakeTableau()
    fake.routes[("GET", f"/api/3.29/sites/{SITE_ID}/projects")] = lambda _r: httpx.Response(
        401, json={"error": {"summary": "Unauthorized", "detail": "nope", "code": "401002"}}
    )
    async with fake.client() as client:
        with pytest.raises(TableauError) as exc:
            await content.list_projects(client)
    assert exc.value.status_code == 502 and exc.value.tableau_status == 401
    assert fake.signins == 2


async def test_bad_pat_sign_in_error_hides_secret() -> None:
    fake = FakeTableau()
    bad = TableauCredentials(SERVER, "mysite", "pat", "wrong-secret")
    async with TableauClient(bad, cache_key="org-2", transport=httpx.MockTransport(fake.handler)) as client:
        with pytest.raises(TableauError) as exc:
            await client.sign_in(force=True)
    assert "Signin Error" in exc.value.message and "wrong-secret" not in exc.value.message


def _target() -> ConnectionTarget:
    return ConnectionTarget(
        name="rds",
        db_type="mssql",
        tableau_class="sqlserver",
        host="db.example.com",
        port=1433,
        database="Analytics",
        username="svc",
        ssl=False,
        password="db-password",
    )


async def test_publish_workbook_binds_only_matching_hosts() -> None:
    fake = FakeTableau()
    puts: list[tuple[str, dict]] = []
    fake.routes[("GET", f"/api/3.29/sites/{SITE_ID}/projects")] = _json(
        {
            "pagination": {"totalAvailable": "2"},
            "projects": {"project": [{"id": "p-default", "name": "default"}, {"id": "p-other", "name": "Other"}]},
        }
    )
    published: dict[str, Any] = {}

    def publish_route(request: httpx.Request) -> httpx.Response:
        published["params"] = dict(request.url.params)
        published["body"] = request.content
        return httpx.Response(201, json={"workbook": {"id": "wb-1", "name": "Book", "webpageUrl": "https://x/wb"}})

    fake.routes[("POST", f"/api/3.29/sites/{SITE_ID}/workbooks")] = publish_route
    fake.routes[("GET", f"/api/3.29/sites/{SITE_ID}/workbooks/wb-1/connections")] = _json(
        {
            "connections": {
                "connection": [
                    {
                        "id": "c1",
                        "type": "sqlserver",
                        "serverAddress": "db.example.com,1433",
                        "datasource": {"name": "Sales"},
                    },
                    {
                        "id": "c2",
                        "type": "sqlserver",
                        "serverAddress": "other.example.com,1433",
                        "datasource": {"name": "Legacy"},
                    },
                    {
                        "id": "c3",
                        "type": "sqlproxy",
                        "serverAddress": "tab.example.com",
                        "datasource": {"name": "Published"},
                    },
                    {"id": "c4", "type": "excel-direct", "serverAddress": "", "datasource": {"name": "Budget"}},
                ]
            }
        }
    )
    for cid in ("c1", "c2"):

        def put_route(request: httpx.Request, cid: str = cid) -> httpx.Response:
            puts.append((cid, json.loads(request.content)))
            return httpx.Response(200, json={"connection": {"id": cid, "embedPassword": True}})

        fake.routes[("PUT", f"/api/3.29/sites/{SITE_ID}/workbooks/wb-1/connections/{cid}")] = put_route
    fake.routes[("GET", f"/api/3.29/sites/{SITE_ID}/workbooks/wb-1/views")] = _json(
        {"views": {"view": [{"id": "v1", "name": "Dash", "contentUrl": "Book/sheets/Dash"}]}}
    )

    twb = (
        b"<workbook xml:base='https://old.example.com'><datasources><datasource>"
        b"<connection class='sqlproxy' dbname='Published' server='old.example.com' /></datasource></datasources></workbook>"
    )
    async with fake.client() as client:
        result = await publish.publish_workbook(client, data=twb, name="Book", target=_target())

    assert published["params"] == {"overwrite": "true", "workbookType": "twb", "skipConnectionCheck": "true"}
    assert b'name="request_payload"' in published["body"] and b'<project id="p-default"' in published["body"]
    assert b"server='tab.example.com'" in published["body"]  # site references normalized before upload
    assert b"db-password" not in published["body"]
    assert [cid for cid, _ in puts] == ["c1"]
    assert puts[0][1] == {
        "connection": {
            "serverAddress": "db.example.com,1433",
            "userName": "svc",
            "password": "db-password",
            "embedPassword": True,
        }
    }
    assert result["credentials_embedded"] == ["Sales"]
    assert {c["datasource_name"] for c in result["unbound_connections"]} == {"Legacy", "Budget"}
    assert result["site_references_rewritten"] == 2
    assert result["views"][0]["url"] == f"{SERVER}/#/site/mysite/views/Book/Dash"
    assert "db-password" not in json.dumps(result)


async def test_publish_datasource_embeds_credentials_in_payload_only() -> None:
    fake = FakeTableau()
    captured: dict[str, bytes] = {}
    fake.routes[("GET", f"/api/3.29/sites/{SITE_ID}/projects")] = _json(
        {"pagination": {"totalAvailable": "1"}, "projects": {"project": [{"id": "p1", "name": "Default"}]}}
    )

    def route(request: httpx.Request) -> httpx.Response:
        captured["body"] = request.content
        captured["query"] = request.url.query
        return httpx.Response(201, json={"datasource": {"id": "ds-1", "name": "SP", "contentUrl": "SP"}})

    fake.routes[("POST", f"/api/3.29/sites/{SITE_ID}/datasources")] = route
    async with fake.client() as client:
        result = await publish.publish_datasource(client, target=_target(), name="SP", schema="marts", table="t")
    body = captured["body"].decode()
    assert '<connectionCredentials name="svc" password="db-password" embed=\'true\' />' in body
    assert body.count("db-password") == 1  # payload only, not the .tds part
    assert "datasourceType=tds" in captured["query"].decode()
    assert result == {
        "id": "ds-1",
        "name": "SP",
        "content_url": "SP",
        "project": {"id": "p1", "name": "Default"},
        "url": None,
    }


async def test_search_maps_content_exploration_hits() -> None:
    fake = FakeTableau()
    fake.routes[("GET", "/api/-/search")] = _json(
        {
            "hits": {
                "items": [
                    {
                        "content": {
                            "type": "workbook",
                            "luid": "wb-1",
                            "title": "Sales",
                            "containerName": "Proj",
                            "id": 7,
                            "modifiedTime": "t1",
                            "repositoryUrl": "Sales",
                        }
                    },
                    {
                        "content": {
                            "type": "view",
                            "luid": "v-1",
                            "title": "Dash",
                            "containerName": "Sales",
                            "projectName": "Proj",
                            "path": "Sales/Dash",
                            "repositoryUrl": "Sales/sheets/Dash",
                            "modifiedTime": "t2",
                        }
                    },
                    {"content": {"type": "unifieddatasource", "datasourceIsPublished": False, "title": "embedded"}},
                    {
                        "content": {
                            "type": "unifieddatasource",
                            "datasourceIsPublished": True,
                            "datasourceLuid": "ds-1",
                            "parentName": "PPC",
                            "containerName": "default",
                            "id": 9,
                            "repositoryUrl": "PPC",
                        }
                    },
                ]
            }
        }
    )
    fake.routes[("GET", f"/api/3.29/sites/{SITE_ID}/workbooks")] = _json(
        {"pagination": {"totalAvailable": "1"}, "workbooks": {"workbook": [{"id": "wb-1", "name": "Sales"}]}}
    )
    async with fake.client() as client:
        results = await content.search(client, "Sales")
    assert [r["kind"] for r in results] == ["workbook", "view", "datasource"]
    assert results[0]["url"] == f"{SERVER}/#/site/mysite/workbooks/7"
    assert results[1]["workbook"] == {"id": "wb-1", "name": "Sales"}
    assert results[2]["id"] == "ds-1" and results[2]["name"] == "PPC"


async def test_resolve_by_name_ambiguous_is_409_and_download_extracts_twb() -> None:
    import io
    import zipfile

    fake = FakeTableau()
    fake.routes[("GET", f"/api/3.29/sites/{SITE_ID}/workbooks")] = lambda r: httpx.Response(
        200,
        json=(
            {
                "pagination": {"totalAvailable": "2"},
                "workbooks": {"workbook": [{"id": "a", "name": "Dup"}, {"id": "b", "name": "Dup"}]},
            }
            if "Dup" in r.url.params.get("filter", "")
            else {"pagination": {"totalAvailable": "1"}, "workbooks": {"workbook": [{"id": "w1", "name": "Pkg"}]}}
        ),
    )
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        zf.writestr("Pkg.twb", b"<workbook/>")
        zf.writestr("Data/Extracts/e.hyper", b"x")
    fake.routes[("GET", f"/api/3.29/sites/{SITE_ID}/workbooks/w1/content")] = lambda r: httpx.Response(
        200, content=buf.getvalue()
    )
    async with fake.client() as client:
        with pytest.raises(TableauError) as exc:
            await content.resolve(client, "workbook", "Dup")
        wb, data = await content.download_workbook(client, "Pkg")
    assert exc.value.status_code == 409 and "a (project" in exc.value.message
    assert wb["id"] == "w1" and data == b"<workbook/>"
    download = next(r for r in fake.requests if r.url.path.endswith("/content"))
    assert download.url.params["includeExtract"] == "false"


async def test_vds_query_limits_rows() -> None:
    fake = FakeTableau()
    ds_id = "cf9dd0c5-05a5-4b0c-8887-189bfa01c2c7"
    fake.routes[("GET", f"/api/3.29/sites/{SITE_ID}/datasources/{ds_id}")] = _json(
        {"datasource": {"id": ds_id, "name": "PPC"}}
    )
    fake.routes[("POST", "/api/v1/vizql-data-service/query-datasource")] = _json(
        {"data": [{"n": i} for i in range(10)]}
    )
    async with fake.client() as client:
        result = await vds.query_datasource(client, ds_id, fields=[{"fieldCaption": "n"}], limit=3)
    assert result["rows"] == [{"n": 0}, {"n": 1}, {"n": 2}] and result["row_count"] == 10 and result["truncated"]
