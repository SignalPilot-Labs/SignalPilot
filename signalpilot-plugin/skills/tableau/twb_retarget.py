#!/usr/bin/env python3
"""Point a Tableau workbook or data source file at new data. Text edits only.

Usage:
    python3 twb_retarget.py IN OUT [options]

Options (use any combination):
    --strip-extracts              Remove <extract> blocks. The file then uses a live connection.
    --db-server HOST              New server for embedded database connections.
    --db-port PORT                New port (SQL Server writes it as HOST,PORT).
    --db-username USER            New user name. The gateway adds the password at publish.
    --db-class CLASS              Only change connections of this class (default: sqlserver).
    --from-server OLD             Only change connections whose server contains OLD.
    --dbname OLD=NEW              Rename a database (repeat for more).
    --site POD SITE               Point published data sources (sqlproxy) at another
                                  Tableau pod and site, for example 10ay.online.tableau.com mysite.
    --published OLD=NEW           Point a published data source reference at another
                                  content_url (repeat for more).
    --files-to-db SCHEMA.DB       Replace file sources (Excel, Google Drive) with tables
                                  [SCHEMA].[sheet] in database DB. Prints the CREATE TABLE
                                  statements the tables need. Needs --db-server.

Get the server, port, and user name for a SignalPilot connection with the
tableau_connection_info tool. The script prints a JSON report of what it changed.
"""

from __future__ import annotations

import json
import re
import sys
from xml.sax.saxutils import quoteattr

EXTRACT_RE = re.compile(r"<extract(?:\s[^>]*)?/>|<extract(?:\s[^>]*)?>.*?</extract>", re.S)
CONN_RE = re.compile(r"<connection\s[^>]*>")
SQL_TYPES = {"string": "nvarchar(255)", "integer": "bigint", "real": "float", "date": "date",
             "datetime": "datetime2", "boolean": "bit"}


def _attr(tag: str, name: str) -> str | None:
    m = re.search(rf"\s{re.escape(name)}='([^']*)'", tag) or re.search(rf'\s{re.escape(name)}="([^"]*)"', tag)
    return m.group(1) if m else None


def _set_attr(tag: str, name: str, value: str) -> str:
    if _attr(tag, name) is not None:
        return re.sub(rf"(\s{re.escape(name)}=)('[^']*'|\"[^\"]*\")", lambda m: m.group(1) + quoteattr(value), tag, count=1)
    return tag.replace("<connection ", f"<connection {name}={quoteattr(value)} ", 1)


def retarget_db(xml: str, opts: dict, report: dict) -> str:
    cls_only = opts.get("db_class", "sqlserver")

    def fix(m: re.Match) -> str:
        tag = m.group(0)
        cls = _attr(tag, "class") or ""
        if cls != cls_only or cls == "sqlproxy":
            return tag
        server = _attr(tag, "server") or ""
        if opts.get("from_server") and opts["from_server"] not in server:
            return tag
        new = tag
        if opts.get("db_server"):
            host = opts["db_server"]
            if cls == "sqlserver" and opts.get("db_port"):
                new = _set_attr(new, "server", f"{host},{opts['db_port']}")
            else:
                new = _set_attr(new, "server", host)
                if opts.get("db_port"):
                    new = _set_attr(new, "port", str(opts["db_port"]))
        if opts.get("db_username"):
            new = _set_attr(new, "username", opts["db_username"])
        dbname = _attr(new, "dbname")
        if dbname and dbname in opts.get("dbname_map", {}):
            new = _set_attr(new, "dbname", opts["dbname_map"][dbname])
        if new != tag:
            report["db_connections_changed"] += 1
        return new

    return CONN_RE.sub(fix, xml)


def retarget_site(xml: str, pod: str, site: str, report: dict) -> str:
    before = xml
    xml = re.sub(r"(class='sqlproxy'[^>]*?server=')[^']*'", lambda m: m.group(1) + pod + "'", xml)
    xml = re.sub(r"(server='[^']*'[^>]*?class='sqlproxy')", lambda m: re.sub(r"server='[^']*'", f"server='{pod}'", m.group(1)), xml)
    xml = re.sub(r"/t/[^/'\"]+/datasources", f"/t/{site}/datasources", xml)
    xml = re.sub(r"(<repository-location [^>]*site=')[^']*'", lambda m: m.group(1) + site + "'", xml)
    xml = re.sub(r"(xml:base=')https?://[^']*'", lambda m: m.group(1) + f"https://{pod}'", xml)
    report["site_rewritten"] = xml != before
    return xml


def retarget_published(xml: str, mapping: dict[str, str], report: dict) -> str:
    for old, new in mapping.items():
        n = xml.count(f"'{old}'") + xml.count(f"/{old}?")
        xml = xml.replace(f"dbname='{old}'", f"dbname='{new}'").replace(f"id='{old}'", f"id='{new}'")
        xml = xml.replace(f"/datasources/{old}?", f"/datasources/{new}?")
        report["published_renamed"][old] = {"to": new, "references": n}
    return xml


def files_to_db(xml: str, schema: str, db: str, opts: dict, report: dict) -> str:
    host, port, user = opts["db_server"], opts.get("db_port"), opts.get("db_username", "")
    server = f"{host},{port}" if port else host
    ddl = []

    def fix_ds(m: re.Match) -> str:
        blk = m.group(0)
        for nc in re.finditer(r"<named-connection [^>]*name='((?:cloudfile:|excel|textscan)[^']+)'>\s*<connection [^>]*/>\s*</named-connection>", blk):
            old = nc.group(1)
            new = "sqlserver." + old.rsplit(".", 1)[-1]
            conn = (f"<named-connection caption={quoteattr(host)} name='{new}'><connection authentication='sqlserver' "
                    f"class='sqlserver' dbname={quoteattr(db)} odbc-native-protocol='yes' one-time-sql='' "
                    f"server={quoteattr(server)} username={quoteattr(user)} /></named-connection>")
            blk = blk.replace(nc.group(0), conn).replace(f"connection='{old}'", f"connection='{new}'")

        def fix_rel(r: re.Match) -> str:
            conn, name, body = r.group(1), r.group(2).replace("&apos;", "'"), r.group(3)
            cols = re.findall(r"<column datatype='([a-z]+)' name='([^']+)' ordinal='\d+' />", body)
            table = re.sub(r"[$'\[\]]", "", name).strip()
            coldefs = ", ".join(f"[{n.replace('&apos;', chr(39))}] {SQL_TYPES.get(t, 'nvarchar(255)')} NULL" for t, n in cols)
            ddl.append(f"CREATE TABLE [{db}].[{schema}].[{table}] ({coldefs})")
            return f"<relation connection='{conn}' name={quoteattr(name)} table={quoteattr(f'[{schema}].[{table}]')} type='table' />"

        blk = re.sub(r"<relation connection='([^']*)' name='([^']+)' table='[^']*' type='table'>\s*<columns [^>]*>(.*?)</columns>\s*</relation>",
                     fix_rel, blk, flags=re.S)
        return re.sub(r"<metadata-record class='capability'>.*?</metadata-record>", "", blk, flags=re.S)

    xml = re.sub(r"<datasource [^>]*>(?:(?!</datasource>).)*?class='(?:cloudfile:[^']*|excel-direct|textscan)'.*?</datasource>",
                 fix_ds, xml, flags=re.S)
    report["file_tables_ddl"] = sorted(set(ddl))
    return xml


def parse(argv: list[str]) -> tuple[str, str, dict]:
    if len(argv) < 3:
        print(__doc__)
        raise SystemExit(2)
    opts: dict = {"dbname_map": {}, "published": {}}
    i = 3
    while i < len(argv):
        a = argv[i]
        if a == "--strip-extracts":
            opts["strip"] = True
        elif a in ("--db-server", "--db-port", "--db-username", "--db-class", "--from-server", "--files-to-db"):
            opts[a[2:].replace("-", "_")] = argv[i + 1]
            i += 1
        elif a == "--dbname":
            old, new = argv[i + 1].split("=", 1)
            opts["dbname_map"][old] = new
            i += 1
        elif a == "--published":
            old, new = argv[i + 1].split("=", 1)
            opts["published"][old] = new
            i += 1
        elif a == "--site":
            opts["site"] = (argv[i + 1].removeprefix("https://").rstrip("/"), argv[i + 2])
            i += 2
        else:
            raise SystemExit(f"unknown option {a!r}")
        i += 1
    return argv[1], argv[2], opts


def main(argv: list[str]) -> int:
    src, dst, opts = parse(argv)
    xml = open(src, encoding="utf-8").read()
    report: dict = {"in": src, "out": dst, "db_connections_changed": 0, "published_renamed": {}}
    if opts.get("strip"):
        n = len(EXTRACT_RE.findall(xml))
        xml = EXTRACT_RE.sub("", xml)
        report["extracts_removed"] = n
    if opts.get("files_to_db"):
        if not opts.get("db_server"):
            raise SystemExit("--files-to-db needs --db-server")
        schema, db = opts["files_to_db"].split(".", 1)
        xml = files_to_db(xml, schema, db, opts, report)
    if opts.get("db_server") or opts.get("db_username") or opts["dbname_map"]:
        xml = retarget_db(xml, opts, report)
    if opts.get("site"):
        xml = retarget_site(xml, *opts["site"], report)
    if opts["published"]:
        xml = retarget_published(xml, opts["published"], report)
    with open(dst, "w", encoding="utf-8") as fh:
        fh.write(xml)
    report["bytes"] = len(xml.encode())
    print(json.dumps(report, indent=1))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
