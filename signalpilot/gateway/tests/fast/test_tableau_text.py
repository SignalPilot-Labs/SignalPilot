"""Tableau pure helpers: site URL parsing, .tds builder, site-reference rewrite, .twbx extraction."""

from __future__ import annotations

import io
import zipfile

import pytest

from gateway.tableau.client import TableauError
from gateway.tableau.connections import ConnectionTarget, build_tds
from gateway.tableau.content import extract_twb, truncate_csv
from gateway.tableau.site_refs import normalize_site_references, normalize_workbook_bytes
from gateway.tableau.urls import TableauSiteUrlError, parse_site_url, site_browser_url

# ── Site URL parsing ────────────────────────────────────────────────────────


@pytest.mark.parametrize(
    ("raw", "server", "site"),
    [
        (
            "https://10ay.online.tableau.com/#/site/acme-analytics/home",
            "https://10ay.online.tableau.com",
            "acme-analytics",
        ),
        (
            "https://10ay.online.tableau.com/#/site/acme-analytics",
            "https://10ay.online.tableau.com",
            "acme-analytics",
        ),
        ("https://tableau.corp.com/#/site/x/views/Wb/Sheet", "https://tableau.corp.com", "x"),
        ("https://tableau.corp.com", "https://tableau.corp.com", ""),
        ("https://tableau.corp.com/", "https://tableau.corp.com", ""),
        (
            "https://10ay.online.tableau.com/t/acme-analytics/views/a",
            "https://10ay.online.tableau.com",
            "acme-analytics",
        ),
        ("  HTTPS://Tableau.Corp.com:8443/#/site/s1  ", "https://tableau.corp.com:8443", "s1"),
        ("http://localhost:8080/#/site/dev", "http://localhost:8080", "dev"),
    ],
)
def test_parse_site_url(raw: str, server: str, site: str) -> None:
    parsed = parse_site_url(raw)
    assert parsed.server_url == server
    assert parsed.site_content_url == site


@pytest.mark.parametrize("raw", ["", "http://tableau.corp.com/#/site/x", "ftp://x.com", "not a url"])
def test_parse_site_url_rejects(raw: str) -> None:
    with pytest.raises(TableauSiteUrlError):
        parse_site_url(raw)


def test_site_browser_url() -> None:
    assert site_browser_url("https://h.com", "abc") == "https://h.com/#/site/abc"
    assert site_browser_url("https://h.com", "") == "https://h.com/#/"


# ── .tds builder ────────────────────────────────────────────────────────────


def _target(db_type: str, cls: str | None, *, ssl: bool = False, port: int | None = None) -> ConnectionTarget:
    return ConnectionTarget(
        name="c",
        db_type=db_type,
        tableau_class=cls,
        host="db.example.com",
        port=port,
        database="Analytics",
        username="svc",
        ssl=ssl,
        password="s3cr3t'<>",
    )


def _tds(*args, **kwargs) -> str:
    """build_tds output with attribute quotes normalized (quoteattr may pick either)."""
    return build_tds(*args, **kwargs).replace('"', "'")


def test_tds_sqlserver_table() -> None:
    tds = _tds(_target("mssql", "sqlserver", port=1433), caption="Sales & Co", schema="marts", table="fct_sales")
    assert "class='sqlserver'" in tds and "authentication='sqlserver'" in tds
    assert "server='db.example.com'" in tds and "port='1433'" in tds and "dbname='Analytics'" in tds
    assert "table='[marts].[fct_sales]'" in tds
    assert "formatted-name='Sales &amp; Co'" in tds
    assert "s3cr3t" not in tds  # the password goes in the publish payload, never in the file
    assert "<extract" not in tds


def test_tds_postgres_ssl_and_default_schema() -> None:
    tds = _tds(_target("postgres", "postgres", ssl=True), caption="x", table="orders")
    assert "class='postgres'" in tds and "authentication='username-password'" in tds
    assert "sslmode='require'" in tds and "port='5432'" in tds
    assert "table='[public].[orders]'" in tds


def test_tds_postgres_without_ssl_and_custom_sql() -> None:
    tds = _tds(_target("postgres", "postgres"), caption="x", sql="SELECT a FROM t WHERE b < 3")
    assert "sslmode" not in tds
    assert "type='text'>SELECT a FROM t WHERE b &lt; 3</relation>" in tds


def test_tds_redshift_always_ssl() -> None:
    tds = _tds(_target("redshift", "redshift"), caption="x", table="t", database="dev")
    assert "class='redshift'" in tds and "sslmode='require'" in tds and "dbname='dev'" in tds


def test_tds_rejects_unsupported_and_bad_source() -> None:
    with pytest.raises(TableauError) as exc:
        build_tds(_target("snowflake", None), caption="x", table="t")
    assert exc.value.status_code == 400 and "not supported yet" in exc.value.message
    with pytest.raises(TableauError):
        build_tds(_target("mssql", "sqlserver"), caption="x", table="t", sql="select 1")
    with pytest.raises(TableauError):
        build_tds(_target("mssql", "sqlserver"), caption="x")


def test_connection_target_hides_password() -> None:
    target = _target("mssql", "sqlserver", port=1433)
    assert "s3cr3t" not in repr(target)
    public = target.public_dict()
    assert "password" not in public and public["sql_server_address"] == "db.example.com,1433"
    assert target.matches_host("DB.example.com,1433")
    assert target.matches_host("db.example.com:1433")
    assert target.matches_host("db.example.com")
    assert not target.matches_host("other.example.com,1433")
    assert not target.matches_host("")


# ── Site-reference rewrite ──────────────────────────────────────────────────

_TWB = """<?xml version='1.0' encoding='utf-8' ?>
<workbook original-version='18.1' source-build='2024.1' version='18.1' xml:base='https://us-east-1.online.tableau.com' xmlns:user='http://www.tableausoftware.com/xml/user'>
  <repository-location id='OldBook' path='/t/oldsite/workbooks' revision='1.0' site='oldsite' />
  <worksheets><worksheet name='S'><repository-location id='S' path='/t/oldsite/workbooks/OldBook' revision='' /></worksheet></worksheets>
  <datasources>
    <datasource caption='Rel' inline='true' name='sqlproxy.2'>
      <repository-location derived-from='/t/oldsite/datasources/Rel?rev=4.2' id='Rel' path='/t/oldsite/datasources' revision='1.0' site='oldsite' />
    </datasource>
    <datasource caption='Plan' inline='true' name='sqlproxy.1'>
      <repository-location derived-from='https://us-east-1.online.tableau.com/t/oldsite/datasources/Plan?rev=1.2' id='Plan' path='/t/oldsite/datasources' revision='1.2' site='oldsite' />
      <connection channel='https' class='sqlproxy' dbname='Plan' directory='/dataserver' port='443' server='us-east-1.online.tableau.com' username='' />
    </datasource>
    <datasource caption='Live' inline='true' name='federated.1'>
      <connection class='federated'><named-connections><named-connection name='sqlserver.1'>
        <connection class='sqlserver' dbname='DW' server='db.example.com,1433' username='u' />
      </named-connection></named-connections></connection>
    </datasource>
  </datasources>
</workbook>
"""


def test_site_refs_rewrite_to_named_site() -> None:
    out, count = normalize_site_references(_TWB, "https://10ay.online.tableau.com", "mysite")
    assert "xml:base='https://10ay.online.tableau.com'" in out
    assert "path='/t/oldsite/workbooks'" not in out  # workbook-level location stripped
    assert "server='10ay.online.tableau.com'" in out
    assert "path='/t/mysite/datasources'" in out and "site='mysite'" in out
    assert "derived-from='https://10ay.online.tableau.com/t/mysite/datasources/Plan?rev=1.2'" in out
    assert "server='db.example.com,1433'" in out  # database connections untouched
    assert "path='/t/oldsite/workbooks/OldBook'" in out  # sheet-level location untouched
    assert "us-east-1" not in out and out.count("oldsite") == 1
    assert "derived-from='/t/mysite/datasources/Rel?rev=4.2'" in out  # relative form stays relative
    assert count == 7  # workbook location, sqlproxy server, 2 ds locations, 2 derived-from, xml:base
    again, count2 = normalize_site_references(out, "https://10ay.online.tableau.com", "mysite")
    assert again == out and count2 == 0


def test_site_refs_default_site_drops_site_attr() -> None:
    out, _ = normalize_site_references(_TWB, "https://tableau.corp.com", "")
    assert "path='/datasources'" in out
    assert "derived-from='https://tableau.corp.com/datasources/Plan?rev=1.2'" in out
    ds_location = next(line for line in out.splitlines() if "id='Plan'" in line)
    assert " site=" not in ds_location


def _zip(entries: dict[str, bytes]) -> bytes:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        for name, data in entries.items():
            zf.writestr(name, data)
    return buf.getvalue()


def test_site_refs_inside_twbx() -> None:
    packaged = _zip({"Book.twb": _TWB.encode(), "Data/Extracts/x.hyper": b"\x00hyper"})
    out, count = normalize_workbook_bytes(packaged, "https://10ay.online.tableau.com", "mysite")
    assert count == 7
    with zipfile.ZipFile(io.BytesIO(out)) as zf:
        assert b"mysite" in zf.read("Book.twb")
        assert zf.read("Data/Extracts/x.hyper") == b"\x00hyper"


def test_site_refs_untouched_bytes_when_nothing_to_do() -> None:
    plain = b"<workbook version='18.1'><datasources /></workbook>"
    assert normalize_workbook_bytes(plain, "https://h.com", "s") == (plain, 0)


# ── .twbx extraction, CSV truncation ────────────────────────────────────────


def test_extract_twb_from_twbx_prefers_root() -> None:
    packaged = _zip({"nested/Other.twb": b"<nested/>", "Book.twb": b"<workbook/>", "Data/x.hyper": b"h"})
    assert extract_twb(packaged) == b"<workbook/>"
    assert extract_twb(b"<workbook/>") == b"<workbook/>"
    with pytest.raises(TableauError):
        extract_twb(_zip({"Data/x.hyper": b"h"}))


def test_truncate_csv_keeps_quoted_newlines() -> None:
    text = 'a,b\n1,"x\ny"\n2,z\n3,w\n'
    assert truncate_csv(text, 2) == 'a,b\n1,"x\ny"\n2,z\n'
