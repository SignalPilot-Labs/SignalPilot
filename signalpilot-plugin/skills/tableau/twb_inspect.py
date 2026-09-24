#!/usr/bin/env python3
"""Summarize a Tableau workbook (.twb) so you can plan an edit.

Usage:
    python3 twb_inspect.py book.twb                   # whole-workbook summary (JSON)
    python3 twb_inspect.py book.twb --dashboard NAME  # sheets and zones of one dashboard
    python3 twb_inspect.py book.twb --worksheet NAME  # shelves, filters, and formulas of one sheet
    python3 twb_inspect.py book.twb --calcs DS_CAPTION  # every calculation in one data source

The summary lists every data source with its kind:
    published  a published data source on the site (class sqlproxy), found by content_url
    database   an embedded database connection (sqlserver, postgres, ...)
    file       a file or cloud-file source (Excel, CSV, Google Drive). Tableau Cloud
               cannot always reach these. Replace them or tell the user.
"""

from __future__ import annotations

import json
import re
import sys
import xml.etree.ElementTree as ET

FILE_CLASSES = ("excel", "textscan", "cloudfile", "hyper", "dataengine", "ogrdirect", "json", "pdf")


def _conn_kind(cls: str) -> str:
    if cls == "sqlproxy":
        return "published"
    if any(cls.startswith(f) for f in FILE_CLASSES):
        return "file"
    return "database"


def _real_datasources(root: ET.Element) -> list[ET.Element]:
    # Worksheets repeat shallow <datasource> stubs; the real ones sit under /workbook/datasources.
    node = root.find("datasources")
    return list(node) if node is not None else []


def _ds_summary(ds: ET.Element) -> dict:
    name = ds.get("name", "")
    out: dict = {"name": name, "caption": ds.get("caption") or name}
    if name == "Parameters":
        out["kind"] = "parameters"
        out["parameters"] = [{"caption": c.get("caption") or c.get("name"), "datatype": c.get("datatype"),
                              "value": c.get("value")} for c in ds.findall("column")]
        return out
    conn = ds.find("connection")
    conns = []
    if conn is not None:
        inner = conn.findall("named-connections/named-connection/connection") or [conn]
        for c in inner:
            cls = c.get("class", "")
            conns.append({k: v for k, v in {"class": cls, "server": c.get("server"), "port": c.get("port"),
                                            "dbname": c.get("dbname"), "username": c.get("username"),
                                            "filename": c.get("filename") or c.get("cloudFileName")}.items() if v})
    kinds = {_conn_kind(c["class"]) for c in conns} or {"unknown"}
    out["kind"] = "published" if "published" in kinds else ("file" if "file" in kinds else "database")
    if out["kind"] == "published":
        out["content_url"] = conn.get("dbname") if conn is not None else None
    out["connections"] = conns
    rels = ds.findall(".//relation[@type='table']")
    out["tables"] = sorted({r.get("table") for r in rels if r.get("table") and r.get("table") != "[sqlproxy]"})
    customs = [r for r in ds.findall(".//relation[@type='text']")]
    if customs:
        out["custom_sql"] = [(r.text or "").strip()[:400] for r in customs]
    cols = ds.findall("column")
    out["columns"] = len(cols)
    out["calculations"] = sum(1 for c in cols if c.find("calculation") is not None)
    out["has_extract"] = ds.find("extract") is not None
    return out


def _fields_on(text: str | None) -> list[str]:
    return re.findall(r"\[[^\]]+\]\.\[[^\]]+\]", text or "")


def _worksheet_summary(ws: ET.Element, captions: dict[str, str]) -> dict:
    view = ws.find("table/view")
    dss = [d.get("caption") or d.get("name") for d in (view.findall("datasources/datasource") if view is not None else [])]
    rows = ws.findtext("table/rows") or ""
    cols = ws.findtext("table/cols") or ""
    marks = [m.get("class") for m in ws.findall("table/panes/pane/mark")]
    return {"name": ws.get("name"), "datasources": dss, "mark": marks[0] if marks else None,
            "rows": _pretty(rows, captions), "cols": _pretty(cols, captions)}


def _pretty(shelf: str, captions: dict[str, str]) -> str:
    def rep(m: re.Match) -> str:
        ds, inst = m.group(1), m.group(2)
        parts = inst.split(":")
        field = parts[1] if len(parts) >= 3 else inst
        return f"{parts[0]}({captions.get(field, field)})" if len(parts) >= 3 and parts[0] not in ("none",) else captions.get(field, field)
    return re.sub(r"\[([^\]]+)\]\.\[([^\]]+)\]", rep, shelf)


def _captions(root: ET.Element) -> dict[str, str]:
    caps = {}
    for ds in _real_datasources(root):
        for c in ds.findall("column"):
            n = (c.get("name") or "").strip("[]")
            if c.get("caption"):
                caps[n] = c.get("caption")
    return caps


def _dashboards(root: ET.Element) -> list[dict]:
    out = []
    for d in root.findall("dashboards/dashboard"):
        sheets = sorted({z.get("name") for z in d.iter("zone") if z.get("name") and not z.get("type-v2")})
        size = d.find("size")
        out.append({"name": d.get("name"), "sheets": sheets,
                    "size": dict(size.attrib) if size is not None else None})
    return out


def summary(root: ET.Element) -> dict:
    caps = _captions(root)
    dss = [_ds_summary(d) for d in _real_datasources(root)]
    wss = [_worksheet_summary(w, caps) for w in root.findall("worksheets/worksheet")]
    return {
        "datasources": dss,
        "dashboards": _dashboards(root),
        "worksheets": wss if len(wss) <= 60 else [{"name": w["name"], "mark": w["mark"]} for w in wss],
        "counts": {"datasources": len(dss), "dashboards": len(root.findall("dashboards/dashboard")),
                   "worksheets": len(wss)},
        "warnings": _warnings(dss),
    }


def _warnings(dss: list[dict]) -> list[str]:
    warn = []
    for d in dss:
        if d.get("kind") == "file":
            warn.append(f"{d['caption']}: file source {[c.get('filename') for c in d['connections']]}. "
                        "Tableau Cloud may not reach it.")
        if d.get("has_extract"):
            warn.append(f"{d['caption']}: has an extract. twb_retarget.py --strip-extracts makes it live.")
    return warn


def worksheet_detail(root: ET.Element, name: str) -> dict:
    ws = next((w for w in root.findall("worksheets/worksheet") if w.get("name") == name), None)
    if ws is None:
        raise SystemExit(f"no worksheet named {name!r}")
    caps = _captions(root)
    formulas = {}
    for ds in _real_datasources(root):
        for c in ds.findall("column"):
            calc = c.find("calculation")
            if calc is not None and calc.get("formula"):
                formulas[(c.get("name") or "").strip("[]")] = (c.get("caption"), calc.get("formula"))
    used = set()
    for dep in ws.iter("column-instance"):
        used.add((dep.get("column") or "").strip("[]"))
    filters = [{"column": _pretty(f.get("column"), caps), "class": f.get("class"),
                "xml": ET.tostring(f, encoding="unicode")[:600]} for f in ws.iter("filter")]
    return {**_worksheet_summary(ws, caps), "filters": filters,
            "encodings": [{e.tag: _pretty(e.get("column"), caps)} for e in ws.findall("table/panes/pane/encodings/*")],
            "calculations": {formulas[k][0] or k: formulas[k][1] for k in used if k in formulas}}


def calcs(root: ET.Element, caption: str) -> list[dict]:
    for ds in _real_datasources(root):
        if (ds.get("caption") or ds.get("name")) == caption:
            return [{"name": c.get("name"), "caption": c.get("caption"), "datatype": c.get("datatype"),
                     "formula": c.find("calculation").get("formula")}
                    for c in ds.findall("column") if c.find("calculation") is not None]
    raise SystemExit(f"no data source with caption {caption!r}")


def main(argv: list[str]) -> int:
    if len(argv) < 2:
        print(__doc__)
        return 2
    root = ET.parse(argv[1]).getroot()
    if "--worksheet" in argv:
        result = worksheet_detail(root, argv[argv.index("--worksheet") + 1])
    elif "--dashboard" in argv:
        name = argv[argv.index("--dashboard") + 1]
        result = next((d for d in _dashboards(root) if d["name"] == name), None) or {"error": f"no dashboard {name!r}"}
    elif "--calcs" in argv:
        result = calcs(root, argv[argv.index("--calcs") + 1])
    else:
        result = summary(root)
    print(json.dumps(result, indent=1, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
