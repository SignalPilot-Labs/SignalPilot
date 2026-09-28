#!/usr/bin/env python3
"""Build a Tableau workbook (.twb) from a JSON spec.

The workbook reads published data sources on the Tableau site, so it has no
database credentials in it. Publish the result with tableau_publish_workbook.
The spec does not need the site: the publish tool points every published data
source reference at the org's Tableau site.

Usage:
    python3 twb_build.py spec.json out.twb

The spec format is in twb_spec.schema.json next to this script. Field
references in rows, cols, and encodings use a small syntax:

    platform               dimension, discrete
    sum(spend_amount)      aggregate: sum avg min max count countd median attr
    month(activity_date)   date part, discrete: year quarter month week day
    tmonth(activity_date)  date truncated, continuous: tyear tquarter tmonth tweek tday
    CPC                    a calculation from the spec (by name)
    :measure_names         Measure Names (use with :measure_values)
"""

from __future__ import annotations

import json
import re
import sys
from xml.sax.saxutils import escape, quoteattr

AGGS = {"sum": "Sum", "avg": "Avg", "min": "Min", "max": "Max", "count": "Count",
        "countd": "CountD", "median": "Median", "attr": "Attr"}
AGG_PREFIX = {"Sum": "sum", "Avg": "avg", "Min": "min", "Max": "max", "Count": "cnt",
              "CountD": "ctd", "Median": "med", "Attr": "attr"}
DATE_PARTS = {"year": ("Year", "yr", "ordinal"), "quarter": ("Quarter", "qr", "ordinal"),
              "month": ("Month", "mn", "ordinal"), "week": ("Week", "wk", "ordinal"),
              "day": ("Day", "dy", "ordinal"),
              "tyear": ("Year-Trunc", "tyr", "quantitative"), "tquarter": ("Quarter-Trunc", "tqr", "quantitative"),
              "tmonth": ("Month-Trunc", "tmn", "quantitative"), "tweek": ("Week-Trunc", "twk", "quantitative"),
              "tday": ("Day-Trunc", "tdy", "quantitative")}
MARKS = {"bar": "Bar", "line": "Line", "area": "Area", "circle": "Circle", "square": "Square",
         "text": "Text", "pie": "Pie", "shape": "Shape", "automatic": "Automatic", "gantt": "GanttBar"}
DATATYPES = {"string": "string", "integer": "integer", "real": "real", "date": "date",
             "datetime": "datetime", "boolean": "boolean", "number": "real", "float": "real", "int": "integer"}
REF_RE = re.compile(r"^\s*([a-z]+)\((.+)\)\s*$")
FORMATS = {"number": "n#,##0", "decimal": "n#,##0.00", "currency": 'c"$"#,##0', "currency2": 'c"$"#,##0.00',
           "percent": "p0.0%", "compact": "n#,##0,K"}


class SpecError(ValueError):
    pass


# Parameters by caption -> {"id": "[Parameter N]", ...}. Set by build().
PARAMS: dict[str, dict] = {}
# Datasource alias -> {calc caption: "Calculation_N"} of the last build (used by the design layer).
LAST_CALC_IDS: dict[str, dict] = {}


def _param_literal(value, dtype: str) -> str:
    if dtype == "string":
        return json.dumps(str(value))
    if dtype in ("date", "datetime"):
        return f"#{value}#"
    if dtype == "boolean":
        return "true" if value else "false"
    return str(value)


def parameters_xml() -> str:
    if not PARAMS:
        return ""
    cols = []
    for caption, p in PARAMS.items():
        dtype, lit = p["type"], _param_literal(p["value"], p["type"])
        role, typ = ("measure", "quantitative") if dtype in ("integer", "real") else ("measure", "nominal")
        if p.get("values"):
            domain = "list"
            inner = "<members>" + "".join(f"<member value={quoteattr(_param_literal(v, dtype))} />" for v in p["values"]) + "</members>"
        elif p.get("range"):
            domain, r = "range", p["range"]
            attrs = "".join(f" {k}={quoteattr(str(r[k2]))}" for k, k2 in (("granularity", "step"), ("max", "max"), ("min", "min")) if k2 in r)
            inner = f"<range{attrs} />"
        else:
            domain, inner = "any", ""
        cols.append(f"<column caption={quoteattr(caption)} datatype='{dtype}' name='{p['id']}' param-domain-type='{domain}' "
                    f"role='{role}' type='{typ}' value={quoteattr(lit)}><calculation class='tableau' formula={quoteattr(lit)} />"
                    f"{inner}</column>")
    return ("\n    <datasource hasconnection='false' inline='true' name='Parameters' version='18.1'><aliases enabled='yes' />"
            + "".join(cols) + "</datasource>")


def _param_formula(formula: str) -> str:
    for caption, p in PARAMS.items():
        formula = formula.replace(f"[Parameters].[{caption}]", f"[Parameters].{p['id']}")
    return formula


def _ds_name(alias: str) -> str:
    return "sqlproxy." + re.sub(r"[^a-z0-9]", "", alias.lower())[:24]


class Datasource:
    def __init__(self, spec: dict, server: str, site: str):
        for key in ("alias", "content_url", "fields"):
            if key not in spec:
                raise SpecError(f"datasource is missing '{key}'")
        self.alias = spec["alias"]
        self.content_url = spec["content_url"]
        self.caption = spec.get("caption") or spec["content_url"]
        self.name = _ds_name(self.alias)
        self.server, self.site = server, site
        self.fields = {}
        self.meta: dict[str, dict] = {}
        for f in spec["fields"]:
            self.meta[f["name"]] = {"caption": f.get("caption"), "format": f.get("format"), "role": f.get("role")}
            dtype = DATATYPES.get(str(f.get("type", "string")).lower())
            if dtype is None:
                raise SpecError(f"field {f.get('name')!r} has unknown type {f.get('type')!r}")
            self.fields[f["name"]] = dtype
        self.calcs: dict[str, dict] = {}

    def add_calc(self, calc: dict, index: int) -> None:
        name = calc["name"]
        if name in self.fields:
            raise SpecError(f"calculation {name!r} has the same name as a field")
        formula = calc["formula"]
        # An LOD expression { FIXED ... : SUM(...) } is row-level, so drop it before the test.
        outer = re.sub(r"\{[^{}]*\}", "0", formula)
        aggregated = bool(re.search(r"\b(SUM|AVG|MIN|MAX|COUNT|COUNTD|MEDIAN|ATTR|WINDOW_\w+|RUNNING_\w+|RANK\w*|LOOKUP|INDEX|TOTAL)\s*\(",
                                    outer, re.I))
        # References to other aggregated calculations are resolved in finish_calcs().
        self.calcs[name] = {"id": f"Calculation_{9000000000000000 + index}", "formula": formula,
                            "type": DATATYPES.get(str(calc.get("type", "real")).lower(), "real"),
                            "role": calc.get("role") or ("measure" if calc.get("type", "real") in
                                                          ("real", "integer", "number") else "dimension"),
                            "aggregated": aggregated, "format": calc.get("format")}

    def finish_calcs(self) -> None:
        """Mark a calculation aggregated when it references an aggregated one (any order)."""
        changed = True
        while changed:
            changed = False
            for name, c in self.calcs.items():
                if c["aggregated"]:
                    continue
                outer = re.sub(r"\{[^{}]*\}", "0", c["formula"])
                if any(f"[{n}]" in outer and o["aggregated"] for n, o in self.calcs.items() if n != name):
                    c["aggregated"] = changed = True

    def column_xml(self) -> str:
        cols = []
        for name, dtype in self.fields.items():
            role, typ = _role_type(dtype, self.meta.get(name, {}).get("role"))
            meta = self.meta.get(name, {})
            extra = (f" caption={quoteattr(meta['caption'])}" if meta.get("caption") else "") + _fmt_attr(meta.get("format"))
            cols.append(f"<column{extra} datatype='{dtype}' name={quoteattr(f'[{name}]')} role='{role}' type='{typ}' />")
        for name, c in self.calcs.items():
            typ = "quantitative" if c["role"] == "measure" else "nominal"
            cols.append(f"<column caption={quoteattr(name)} datatype='{c['type']}'{_fmt_attr(c.get('format'))} name='[{c['id']}]' "
                        f"role='{c['role']}' type='{typ}'><calculation class='tableau' "
                        f"formula={quoteattr(self._formula(c['formula']))} /></column>")
        return "\n      ".join(cols)

    def _formula(self, formula: str) -> str:
        # Calculations may reference other calculations by caption; Tableau needs the internal id.
        for name, c in self.calcs.items():
            formula = formula.replace(f"[{name}]", f"[{c['id']}]")
        return _param_formula(formula)

    def xml(self) -> str:
        return f"""
    <datasource caption={quoteattr(self.caption)} inline='true' name='{self.name}' version='18.1'>
      <repository-location id={quoteattr(self.content_url)} path='/t/{self.site}/datasources' revision='1.0' site='{self.site}' />
      <connection channel='https' class='sqlproxy' dbname={quoteattr(self.content_url)} directory='/dataserver' port='443' server='{self.server}' username='' workgroup-auth-mode='prompt'>
        <relation name='sqlproxy' table='[sqlproxy]' type='table' />
      </connection>
      <aliases enabled='yes' />
      {self.column_xml()}
    </datasource>""" if self.site else f"""
    <datasource caption={quoteattr(self.caption)} inline='true' name='{self.name}' version='18.1'>
      <repository-location id={quoteattr(self.content_url)} path='/datasources' revision='1.0' />
      <connection channel='https' class='sqlproxy' dbname={quoteattr(self.content_url)} directory='/dataserver' port='443' server='{self.server}' username='' workgroup-auth-mode='prompt'>
        <relation name='sqlproxy' table='[sqlproxy]' type='table' />
      </connection>
      <aliases enabled='yes' />
      {self.column_xml()}
    </datasource>"""


def _fmt_attr(fmt: str | None) -> str:
    if not fmt:
        return ""
    return f" default-format={quoteattr(FORMATS.get(fmt, fmt))}"


def _role_type(dtype: str, role: str | None = None) -> tuple[str, str]:
    if role == "dimension":
        return "dimension", "ordinal" if dtype in ("real", "integer", "date", "datetime") else "nominal"
    if dtype in ("real", "integer"):
        return "measure", "quantitative"
    if dtype in ("date", "datetime"):
        return "dimension", "ordinal"
    return "dimension", "nominal"


class Ref:
    """One parsed field reference: the column-instance XML and the shelf token."""

    def __init__(self, ds: Datasource, text: str):
        self.ds = ds
        text = text.strip()
        if text in (":measure_names", ":measure_values"):
            self.special = text
            self.token = f"[{ds.name}].[:Measure Names]" if text == ":measure_names" else f"[{ds.name}].[Multiple Values]"
            self.instance, self.column = "", ""
            return
        self.special = None
        m = REF_RE.match(text)
        func, field = (m.group(1).lower(), m.group(2).strip()) if m else ("", text)
        calc = ds.calcs.get(field)
        if calc is None and field not in ds.fields:
            raise SpecError(f"unknown field {field!r} in datasource {ds.alias!r}. "
                            f"Known: {sorted(ds.fields)[:40]}")
        col = f"[{calc['id']}]" if calc else f"[{field}]"
        key = calc["id"] if calc else field
        dtype = calc["type"] if calc else ds.fields[field]
        if calc and calc["aggregated"]:
            if func:
                raise SpecError(f"{field!r} is already aggregated; use it without {func}()")
            # Aggregated text and true/false calculations are discrete (nk); numbers are continuous (qk).
            deriv, prefix, typ = "User", "usr", ("quantitative" if calc["type"] in ("real", "integer") else "nominal")
        elif func in AGGS:
            deriv = AGGS[func]
            prefix, typ = AGG_PREFIX[deriv], "quantitative"
        elif func in DATE_PARTS:
            if dtype not in ("date", "datetime"):
                raise SpecError(f"{func}() needs a date field, {field!r} is {dtype}")
            deriv, prefix, typ = DATE_PARTS[func]
        elif func:
            raise SpecError(f"unknown function {func!r} in {text!r}")
        else:
            role, typ0 = _role_type(dtype, ds.meta.get(field, {}).get("role")) if not calc else (calc["role"], "quantitative" if calc["role"] == "measure" else "nominal")
            if role == "measure":
                deriv, prefix, typ = "Sum", "sum", "quantitative"
            else:
                deriv, prefix, typ = "None", "none", "nominal" if typ0 == "nominal" else "ordinal"
        suffix = {"quantitative": "qk", "nominal": "nk", "ordinal": "ok"}[typ]
        self.name = f"[{prefix}:{key}:{suffix}]"
        self.token = f"[{ds.name}].{self.name}"
        self.column = col
        self.instance = (f"<column-instance column={quoteattr(col)} derivation='{deriv}' "
                         f"name={quoteattr(self.name)} pivot='key' type='{typ}' />")
        self.is_measure = typ == "quantitative" and deriv not in ("None",) and not func in DATE_PARTS
        self.dtype = dtype
        self.label = text


def _shelf(refs: list[Ref]) -> str:
    return " / ".join(r.token for r in refs)


def _filter_xml(ds: Datasource, f: dict) -> tuple[str, list[Ref]]:
    ref = Ref(ds, f["field"])
    if "values" in f:
        members = "".join(f"<groupfilter function='member' level={quoteattr(ref.name)} "
                          f"member={quoteattr(json.dumps(v) if isinstance(v, str) else (str(v).lower() if isinstance(v, bool) else str(v)))} />"
                          for v in f["values"])
        func = "union" if len(f["values"]) > 1 else None
        inner = (f"<groupfilter function='union' user:op='manual'>{members}</groupfilter>" if func
                 else members.replace("<groupfilter ", "<groupfilter user:ui-domain='database' user:ui-enumeration='inclusive' user:ui-marker='enumerate' ", 1))
        if f.get("exclude"):
            inner = f"<groupfilter function='except' user:ui-enumeration='exclusive'><groupfilter function='level-members' level={quoteattr(ref.name)} />{inner}</groupfilter>"
        return f"<filter class='categorical' column={quoteattr(ref.token)}>{inner}</filter>", [ref]
    if "min" in f or "max" in f:
        parts = []
        if "min" in f:
            parts.append(f"<min>{escape(_lit(f['min'], ref.dtype))}</min>")
        if "max" in f:
            parts.append(f"<max>{escape(_lit(f['max'], ref.dtype))}</max>")
        incl = "range" if "min" in f and "max" in f else ("min" if "min" in f else "max")
        return (f"<filter class='quantitative' column={quoteattr(ref.token)} included-values='in-range'>"
                f"{''.join(parts)}</filter>".replace("in-range", {"range": "in-range", "min": "in-range-or-null", "max": "in-range-or-null"}[incl]), [ref])
    if "last_n" in f:
        unit = f.get("unit", "month")
        return (f"<filter class='relative-date' column={quoteattr(ref.token)} first-period='-{int(f['last_n']) - 1}' "
                f"include-future='true' include-null='false' last-period='0' period-type='{unit}' />", [ref])
    raise SpecError(f"filter on {f['field']!r} needs values, min/max, or last_n")


def _lit(value, dtype: str) -> str:
    if dtype in ("date", "datetime"):
        return f"#{value}#"
    return str(value)


def worksheet_xml(ws: dict, dss: dict[str, Datasource]) -> str:
    name = ws["name"]
    ds = dss.get(ws.get("datasource") or next(iter(dss)))
    if ds is None:
        raise SpecError(f"worksheet {name!r} names unknown datasource {ws.get('datasource')!r}")
    mark = MARKS.get(str(ws.get("mark", "automatic")).lower())
    if mark is None:
        raise SpecError(f"worksheet {name!r} has unknown mark {ws.get('mark')!r}; use one of {sorted(MARKS)}")
    rows = [Ref(ds, r) for r in ws.get("rows", [])]
    cols = [Ref(ds, c) for c in ws.get("cols", [])]
    enc_refs, enc_xml = [], []
    for enc in ("color", "size", "label", "detail", "tooltip", "text", "shape"):
        vals = ws.get(enc)
        if vals is None:
            continue
        for v in (vals if isinstance(vals, list) else [vals]):
            r = Ref(ds, v)
            enc_refs.append(r)
            tag = "text" if enc == "label" else enc
            enc_xml.append(f"<{tag} column={quoteattr(r.token)} />")
    filters, filt_refs = [], []
    for f in ws.get("filters", []):
        x, refs = _filter_xml(ds, f)
        filters.append(x)
        filt_refs += refs
    has_measure_names = any(r.special for r in rows + cols + enc_refs)
    if has_measure_names:
        mv = [Ref(ds, m) for m in ws.get("measure_values", [])]
        if not mv:
            raise SpecError(f"worksheet {name!r} uses :measure_names; list the measures in measure_values")
        enc_refs += mv
        members = "".join(f"<groupfilter function='member' level='[:Measure Names]' member={quoteattr(json.dumps(r.token))} />" for r in mv)
        filters.append(f"<filter class='categorical' column='[{ds.name}].[:Measure Names]'>"
                       f"<groupfilter function='union' user:op='manual'>{members}</groupfilter></filter>")
        # Without a manual sort Tableau orders Measure Names alphabetically; keep the spec order.
        buckets = "".join(f"<bucket>{escape(json.dumps(r.token))}</bucket>" for r in mv)
        filters.append(f"<manual-sort column='[{ds.name}].[:Measure Names]' direction='ASC'>"
                       f"<dictionary>{buckets}</dictionary></manual-sort>")
    seen, deps = set(), []
    for r in rows + cols + enc_refs + filt_refs:
        if r.special or r.name in seen:
            continue
        seen.add(r.name)
        deps.append(r.instance)
    # declare base columns used
    used_cols = {r.column for r in rows + cols + enc_refs + filt_refs if not r.special}
    col_decls = [line for line in ds.column_xml().split("\n      ")
                 if any(f"name={quoteattr(c)}" in line or f"name='{c}'" in line for c in used_cols)]
    # Follow calculations that reference other calculations, so a parameter used only
    # by a helper calculation is still declared on the sheet.
    by_id = {f"[{c['id']}]": c for c in ds.calcs.values()}
    reached, todo = set(), [c for c in used_cols if c in by_id]
    while todo:
        cid = todo.pop()
        if cid in reached:
            continue
        reached.add(cid)
        todo += [ref for ref in re.findall(r"\[Calculation_\d+\]", ds._formula(by_id[cid]["formula"])) if ref in by_id]
    used_params = sorted({pid for cid in reached
                          for pid in re.findall(r"\[Parameters\]\.(\[Parameter \d+\])", ds._formula(by_id[cid]["formula"]))})
    param_ds, param_deps = "", ""
    if used_params:
        param_ds = "<datasource name='Parameters' />"
        decl = [line for line in parameters_xml().split("<column ")[1:] if any(f"name='{pid}'" in line for pid in used_params)]
        param_deps = ("<datasource-dependencies datasource='Parameters'>"
                      + "".join(re.sub(r"<members>.*?</members>|<range[^>]*/>", "", "<column " + line.split("</datasource>")[0])
                                for line in decl) + "</datasource-dependencies>")
    sort_xml = ""
    if ws.get("sort"):
        s = ws["sort"]
        by, using = Ref(ds, s["field"]), Ref(ds, s["by"]) if s.get("by") else None
        direction = "DESC" if str(s.get("direction", "desc")).lower().startswith("d") else "ASC"
        if using is not None:
            if using.name not in seen:
                deps.append(using.instance)
                seen.add(using.name)
            sort_xml = (f"<sort class='computed' column={quoteattr(by.token)} direction='{direction}' "
                        f"using={quoteattr(using.token)} />")
        elif s.get("order"):
            buckets = "".join(f"<bucket>{escape(json.dumps(v) if isinstance(v, str) else str(v))}</bucket>"
                              for v in s["order"])
            sort_xml = (f"<manual-sort column={quoteattr(by.token)} direction='ASC'>"
                        f"<dictionary>{buckets}</dictionary></manual-sort>")
        else:
            sort_xml = f"<sort class='alphabetic' column={quoteattr(by.token)} direction='{direction}' />"
    title = ws.get("title")
    title_xml = (f"<layout-options><title><formatted-text><run>{escape(title)}</run></formatted-text></title></layout-options>"
                 if title else "")
    encodings = f"<encodings>{''.join(enc_xml)}</encodings>" if enc_xml else ""
    kpi_label, table_style = "", "<style />"
    if ws.get("kpi"):
        if mark != "Text" or not ws.get("text"):
            raise SpecError(f"worksheet {name!r}: kpi needs mark 'text' and a 'text' measure")
        token = next(r.token for r in enc_refs if not r.special)
        run = f"<![CDATA[<{token}>]]>"
        size = int(ws.get("kpi_font_size", 28))
        caption = ws.get("kpi_caption")
        caption_runs = (f"<run fontalignment='1' fontcolor='#898989' fontsize='12'>{escape(caption.upper())}</run>"
                        "<run fontalignment='1'>Æ&#10;</run>") if caption else ""
        kpi_label = (f"<customized-label><formatted-text>{caption_runs}<run bold='true' fontalignment='1' "
                     f"fontsize='{size}'>{run}</run></formatted-text></customized-label>"
                     "<style><style-rule element='mark'><format attr='mark-labels-show' value='true' />"
                     "<format attr='mark-labels-cull' value='true' /></style-rule></style>")
        table_style = ("<style><style-rule element='cell'><format attr='text-align' value='center' />"
                       "<format attr='vertical-align' value='center' /></style-rule></style>")
    mark_labels = ("<style><style-rule element='mark'><format attr='mark-labels-show' value='true' />"
                   "<format attr='mark-labels-cull' value='true' /></style-rule></style>") if ws.get("show_labels") else ""
    return f"""
    <worksheet name={quoteattr(name)}>
      {title_xml}
      <table>
        <view>
          <datasources><datasource caption={quoteattr(ds.caption)} name='{ds.name}' />{param_ds}</datasources>
          {param_deps}
          <datasource-dependencies datasource='{ds.name}'>
            {"".join(col_decls)}
            {"".join(deps)}
          </datasource-dependencies>
          {"".join(filters)}
          {sort_xml}
          <aggregation value='true' />
        </view>
        {table_style}
        <panes><pane selection-relaxation-option='selection-relaxation-allow'><view><breakdown value='auto' /></view><mark class='{mark}' />{encodings}{kpi_label}{mark_labels}</pane></panes>
        <rows>{escape(_shelf(rows))}</rows>
        <cols>{escape(_shelf(cols))}</cols>
      </table>
      <simple-id uuid='{{{_uuid(name)}}}' />
    </worksheet>"""


def _uuid(seed: str) -> str:
    import hashlib
    h = hashlib.md5(seed.encode()).hexdigest().upper()
    return f"{h[:8]}-{h[8:12]}-{h[12:16]}-{h[16:20]}-{h[20:32]}"


def dashboard_xml(d: dict, sheet_names: set[str]) -> tuple[str, str]:
    w, h = int(d.get("width", 1200)), int(d.get("height", 800))
    layout = d.get("layout") or [[s] for s in d.get("sheets", [])]
    if not layout:
        raise SpecError(f"dashboard {d['name']!r} has no layout")
    title = d.get("title")
    zid = [10]

    def nid() -> int:
        zid[0] += 1
        return zid[0]

    top = 0
    zones = []
    if title:
        zones.append(f"<zone h='6000' id='{nid()}' type-v2='text' w='100000' x='0' y='0'>"
                     f"<formatted-text><run fontsize='18' bold='true'>{escape(title)}</run></formatted-text></zone>")
        top = 6000
    weights = d.get("row_heights") or [1] * len(layout)
    total = sum(weights)
    y = top
    avail = 100000 - top
    for row, weight in zip(layout, weights):
        rh = int(avail * weight / total)
        cw = 100000 // len(row)
        cells = []
        for i, sheet in enumerate(row):
            if sheet.startswith("text:"):
                cells.append(f"<zone h='{rh}' id='{nid()}' type-v2='text' w='{cw}' x='{i * cw}' y='{y}'>"
                             f"<formatted-text><run fontsize='12' bold='true'>{escape(sheet[5:])}</run></formatted-text></zone>")
                continue
            if sheet.startswith("param:"):
                p = PARAMS.get(sheet[6:])
                if p is None:
                    raise SpecError(f"dashboard {d['name']!r} shows unknown parameter {sheet[6:]!r}")
                cells.append(f"<zone h='{rh}' id='{nid()}' mode='compact' param='[Parameters].{p['id']}' "
                             f"type-v2='paramctrl' w='{cw}' x='{i * cw}' y='{y}' />")
                continue
            if sheet not in sheet_names:
                raise SpecError(f"dashboard {d['name']!r} places unknown worksheet {sheet!r}")
            cells.append(f"<zone h='{rh}' id='{nid()}' name={quoteattr(sheet)} w='{cw}' x='{i * cw}' y='{y}' />")
        zones.append(f"<zone h='{rh}' id='{nid()}' param='horz' type-v2='layout-flow' w='100000' x='0' y='{y}'>"
                     + "".join(cells) + "</zone>")
        y += rh
    placed = [s for row in layout for s in row if not s.startswith(("param:", "text:"))]
    xml = f"""
    <dashboard name={quoteattr(d['name'])}>
      <style />
      <size maxheight='{h}' maxwidth='{w}' minheight='{h}' minwidth='{w}' />
      <zones>
        <zone h='100000' id='1' type-v2='layout-basic' w='100000' x='0' y='0'>
          <zone h='100000' id='2' param='vert' type-v2='layout-flow' w='100000' x='0' y='0'>
            {"".join(zones)}
          </zone>
        </zone>
      </zones>
      <simple-id uuid='{{{_uuid(d['name'])}}}' />
    </dashboard>"""
    viewpoints = "".join(f"<viewpoint name={quoteattr(s)}><zoom type='entire-view' /></viewpoint>" for s in placed)
    window = (f"<window class='dashboard' maximized='true' name={quoteattr(d['name'])}>"
              f"<viewpoints>{viewpoints}</viewpoints><active id='-1' /></window>")
    return xml, window


def worksheet_window(name: str, hidden: bool = False) -> str:
    # Sheets placed on a dashboard are hidden, like Tableau does, so only dashboards
    # (and stand-alone sheets) publish as views.
    flag = " hidden='true'" if hidden else ""
    return (f"<window class='worksheet'{flag} name={quoteattr(name)}><cards><edge name='left'><strip size='160'>"
            "<card type='pages' /><card type='filters' /><card type='marks' /></strip></edge><edge name='top'>"
            "<strip size='2147483647'><card type='columns' /></strip><strip size='2147483647'><card type='rows' />"
            "</strip><strip size='31'><card type='title' /></strip></edge></cards>"
            "<viewpoint><zoom type='entire-view' /></viewpoint></window>")


def _build_core(spec: dict) -> str:
    # tableau_publish_workbook points every published data source reference at the
    # org's site, so server and site are optional. The placeholders keep the XML valid.
    server = str(spec.get("server") or "tableau.invalid").removeprefix("https://").removeprefix("http://").rstrip("/")
    site = spec.get("site", "") if spec.get("server") else spec.get("site", "site")
    PARAMS.clear()
    for i, p in enumerate(spec.get("parameters", []), start=1):
        dtype = DATATYPES.get(str(p.get("type", "string")).lower())
        if dtype is None or "name" not in p or "value" not in p:
            raise SpecError(f"parameter {p.get('name')!r} needs name, type, and value")
        PARAMS[p["name"]] = {"id": f"[Parameter {i}]", "type": dtype, "value": p["value"],
                             "values": p.get("values"), "range": p.get("range")}
    dss = {d["alias"]: Datasource(d, server, site) for d in spec.get("datasources", [])}
    if not dss:
        raise SpecError("spec needs at least one datasource")
    for i, c in enumerate(spec.get("calculations", [])):
        alias = c.get("datasource") or next(iter(dss))
        if alias not in dss:
            raise SpecError(f"calculation {c.get('name')!r} names unknown datasource {alias!r}")
        dss[alias].add_calc(c, i)
    for d in dss.values():
        d.finish_calcs()
    sheets = spec.get("worksheets", [])
    if not sheets:
        raise SpecError("spec needs at least one worksheet")
    names = [s["name"] for s in sheets]
    if len(set(names)) != len(names):
        raise SpecError("worksheet names must be unique")
    ws_xml = "".join(worksheet_xml(s, dss) for s in sheets)
    dash_xml, dash_windows = [], []
    for d in spec.get("dashboards", []):
        if d["name"] in names:
            raise SpecError(f"dashboard {d['name']!r} has the same name as a worksheet")
        x, win = dashboard_xml(d, set(names))
        dash_xml.append(x)
        dash_windows.append(win)
    on_dash = {c for d in spec.get("dashboards", []) for row in (d.get("layout") or [[x] for x in d.get("sheets", [])])
               for c in row} if not spec.get("show_sheets") else set()
    windows = "".join(worksheet_window(n, n in on_dash) for n in names) + "".join(dash_windows)
    LAST_CALC_IDS.clear()
    LAST_CALC_IDS.update({a: {n: c["id"] for n, c in d.calcs.items()} for a, d in dss.items()})
    ds_xml = parameters_xml() + "".join(d.xml() for d in dss.values())
    return f"""<?xml version='1.0' encoding='utf-8' ?>
<workbook original-version='18.1' source-build='2024.2.0 (20242.24.0613.2210)' source-platform='linux' version='18.1' xml:base='https://{server}' xmlns:user='http://www.tableausoftware.com/xml/user'>
  <preferences><preference name='ui.encoding.shelf.height' value='24' /><preference name='ui.shelf.height' value='26' /></preferences>
  <datasources>{ds_xml}
  </datasources>
  <worksheets>{ws_xml}
  </worksheets>
  <dashboards>{"".join(dash_xml)}
  </dashboards>
  <windows>{windows}
  </windows>
</workbook>
"""


def build(spec: dict) -> str:
    """Build a workbook. A spec with "theme" goes through the design layer (twb_design, twb_layout)."""
    if not spec.get("theme"):
        return _build_core(spec)
    import twb_design
    import twb_layout
    spec = twb_design.expand(spec)
    twb_layout.prepare(spec)
    xml = twb_design.decorate(_build_core(spec), spec, LAST_CALC_IDS)
    return twb_layout.apply(xml, spec, PARAMS)


def main(argv: list[str]) -> int:
    if len(argv) != 3:
        print(__doc__)
        return 2
    try:
        spec = json.load(open(argv[1], encoding="utf-8"))
        xml = build(spec)
    except (SpecError, KeyError, json.JSONDecodeError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1
    with open(argv[2], "w", encoding="utf-8") as fh:
        fh.write(xml)
    print(json.dumps({"path": argv[2], "bytes": len(xml.encode()),
                      "worksheets": [s["name"] for s in spec["worksheets"]],
                      "dashboards": [d["name"] for d in spec.get("dashboards", [])]}))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
