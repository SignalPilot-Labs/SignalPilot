"""Design layer for twb_build.py: theme, declarative components, and chart styling.

A spec turns this on with a top-level "theme" (for example {"name": "sp"}). Then:

- Worksheets can use a "kind":
    card         KPI card: label, big value, colored change vs a comparison, optional second row (for example YTD)
    combo        bars (or a line) with a second line on the same axis: actual vs plan, this year vs last year
    ranked_bars  horizontal bars, sorted, labeled, value axis hidden
    status_bars  bars colored by bands (on plan / near / behind)
    table        text table of measures, banded rows, right-aligned numbers
  Plain worksheets (mark + rows/cols) still work and get the theme's clean chrome.
- Field references can use mname(date_field): a Jan..Dec month axis, sorted and horizontal.
- Dashboards can use "rows" (see twb_layout.py) for a floating card grid with a header and a footer.

expand(spec) runs before the XML build; decorate(xml, spec) runs after it.
"""

from __future__ import annotations

import json
import re
from xml.sax.saxutils import escape, quoteattr

THEMES = {
    "sp": {"canvas": "#EEF1F4", "card": "#FFFFFF", "grid": "#E6E9ED", "ink": "#1B2229", "ink2": "#4D5760",
           "ink3": "#8A949E", "accent": "#1F6F8B", "reference": "#B9C2CB", "plan": "#E08A3C", "good": "#2E8B57",
           "bad": "#C0392B", "warn": "#E0A13C", "band": "#F5F7F9", "font": "Tableau Book", "semi": "Tableau Semibold"},
}
MONTHS = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"]
AGG_RE = re.compile(r"^\s*(sum|avg|min|max|count|countd|median)\((.+)\)\s*$", re.I)


def theme(spec: dict) -> dict:
    t = spec.get("theme") or {}
    base = dict(THEMES.get(t.get("name", "sp"), THEMES["sp"]))
    base.update({k: v for k, v in t.items() if k != "name"})
    return base


def color(spec: dict, name: str | None, default: str = "accent") -> str:
    t = theme(spec)
    name = name or default
    return name if name.startswith("#") else t.get(name, t[default])


# ---------------------------------------------------------------- expand (before build)
class _Ctx:
    def __init__(self, spec: dict):
        self.spec = spec
        self.first = spec["datasources"][0]["alias"]
        self.names = {(c.get("datasource") or self.first, c["name"]) for c in spec.get("calculations", [])}

    def add_calc(self, ds: str, name: str, formula: str, type_: str = "real", fmt=None, role=None) -> str:
        if (ds, name) not in self.names:
            calc = {"datasource": ds, "name": name, "formula": formula, "type": type_}
            if fmt:
                calc["format"] = fmt
            if role:
                calc["role"] = role
            self.spec.setdefault("calculations", []).append(calc)
            self.names.add((ds, name))
        return name

    def measure(self, ds: str, ref: str, fmt=None) -> str:
        """A calc name for a measure reference, so the design layer always has a calc token."""
        if (ds, ref) in self.names:
            return ref
        m = AGG_RE.match(ref)
        func, field = (m.group(1).upper(), m.group(2)) if m else ("SUM", ref)
        return self.add_calc(ds, f"{func.title()} of {field}", f"{func}([{field}])", fmt=fmt)

    def mname(self, ds: str, ref: str) -> tuple[str, dict | None]:
        m = re.match(r"^\s*mname\((.+)\)\s*$", ref)
        if not m:
            return ref, None
        field = m.group(1).strip()
        name = self.add_calc(ds, f"Month of {field}", f"LEFT(DATENAME('month', [{field}]), 3)", "string", role="dimension")
        return name, {"field": name, "order": MONTHS}


def _delta(ctx: _Ctx, ds: str, key: str, compare: dict, lead: str = "") -> tuple[str, str]:
    cur, prev = compare["current"], compare["previous"]
    if compare.get("unit") == "points":
        v, unit = f"(([{cur}] - [{prev}]) * 100)", " pts"
    else:
        v, unit = f"(([{cur}] - [{prev}]) / ABS([{prev}]) * 100)", "%"
    guard = f"NOT ISNULL([{prev}]) AND [{prev}] <> 0"
    up = ctx.add_calc(ds, f"{key} up", f'IF {guard} AND {v} >= 0 THEN "{lead}▲ " + STR(ROUND({v}, 1)) + "{unit}" END', "string", role="measure")
    dn = ctx.add_calc(ds, f"{key} down", f'IF {guard} AND {v} < 0 THEN "{lead}▼ " + STR(ROUND(ABS({v}), 1)) + "{unit}" END', "string", role="measure")
    return up, dn


def expand(spec: dict) -> dict:
    """Rewrite design kinds into plain worksheets and calcs the core builder understands."""
    spec = json.loads(json.dumps(spec))
    ctx = _Ctx(spec)
    out = []
    for ws in spec.get("worksheets", []):
        ds = ws.get("datasource") or ctx.first
        kind = ws.get("kind")
        base = {k: ws[k] for k in ("name", "datasource", "filters", "title") if k in ws}
        base.setdefault("datasource", ds)
        design = {"kind": kind or "chart"}
        if kind == "card":
            value = ctx.measure(ds, ws["value"])
            fields = [value]
            design.update(label=ws.get("label", ws["name"]).upper(), value=value, label_field=ws.get("label_field"),
                          note=ws.get("note"))
            if ws.get("label_field"):
                fields.append(ws["label_field"])
            for part, lead in (("compare", ""), ("secondary", " ")):
                block = ws.get(part)
                if not block:
                    continue
                if part == "secondary":
                    sval = ctx.measure(ds, block["value"])
                    fields.append(sval)
                    design["secondary"] = {"label": block.get("label", "YTD"), "value": sval}
                    block = block.get("compare")
                    if not block:
                        continue
                up, dn = _delta(ctx, ds, f"{ws['name']} {part}", block, lead)
                prev = ctx.measure(ds, block["previous"])
                fields += [up, dn, prev]
                info = {"up": up, "down": dn, "previous": prev, "text": block.get("text", "vs"), "text_field": block.get("text_field")}
                if block.get("text_field"):
                    fields.append(block["text_field"])
                if part == "compare":
                    design["compare"] = info
                else:
                    design["secondary"]["compare"] = info
            out.append(dict(base, mark="text", text=list(dict.fromkeys(fields)), _design=design))
        elif kind == "combo":
            x, sort = ctx.mname(ds, ws["x"])
            first, second = ctx.measure(ds, ws["bar"]), ctx.measure(ds, ws["line"])
            label = ctx.measure(ds, ws["label"]) if ws.get("label") else None
            design.update(first=first, second=second, label=label, marks=ws.get("marks", ["bar", "line"]),
                          colors=ws.get("colors", ["accent", "reference"]), legend=ws.get("legend"), range=ws.get("range"))
            sheet = dict(base, mark=design["marks"][0], cols=[x], rows=[first, second], _design=design)
            if sort or ws.get("sort"):
                sheet["sort"] = ws.get("sort") or sort
            if label and label not in (first, second):
                sheet["tooltip"] = [label]
            out.append(sheet)
        elif kind == "ranked_bars":
            value = ctx.measure(ds, ws["value"])
            design.update(value=value, color=ws.get("color", "accent"))
            out.append(dict(base, mark="bar", rows=[ws["category"]], cols=[value], show_labels=True,
                            sort={"field": ws["category"], "by": value, "direction": ws.get("direction", "desc")}, _design=design))
        elif kind == "status_bars":
            value = ctx.measure(ds, ws["value"])
            bands = ws.get("bands") or [{"label": "On target", "min": 1, "color": "good"},
                                        {"label": "Near target", "min": 0.8, "color": "warn"},
                                        {"label": "Below target", "color": "bad"}]
            names, upper = [], None
            for b in bands:
                cond = []
                if b.get("min") is not None:
                    cond.append(f"[{value}] >= {b['min']}")
                if upper is not None:
                    cond.append(f"[{value}] < {upper}")
                formula = f"IF {' AND '.join(cond) or 'TRUE'} THEN [{value}] END"
                names.append(ctx.add_calc(ds, b["label"], formula, fmt=ws.get("format", "p0%")))
                upper = b.get("min")
            design.update(value=value, bands=[(n, b.get("color", "accent")) for n, b in zip(names, bands)])
            out.append(dict(base, mark="bar", rows=[ws["category"]], cols=[":measure_values"], color=":measure_names",
                            measure_values=names, show_labels=True,
                            sort={"field": ws["category"], "by": value, "direction": "desc"}, _design=design))
        elif kind == "table":
            cols = [ctx.measure(ds, m) for m in ws["columns"]]
            design.update(row_fields=ws["rows"])
            sheet = dict(base, mark="text", rows=ws["rows"], cols=[":measure_names"], text=":measure_values", measure_values=cols, _design=design)
            if ws.get("sort"):
                sheet["sort"] = ws["sort"]
            out.append(sheet)
        else:
            ws = dict(ws)
            for shelf in ("rows", "cols"):
                refs = []
                for r in ws.get(shelf, []):
                    name, sort = ctx.mname(ds, r)
                    refs.append(name)
                    if sort and not ws.get("sort"):
                        ws["sort"] = sort
                if refs:
                    ws[shelf] = refs
            ws["_design"] = dict(design, legend=ws.pop("legend", None), direct_labels=ws.pop("direct_labels", False))
            out.append(ws)
    spec["worksheets"] = out
    # Layout rows -> a plain layout for the core builder (twb_layout replaces the zones later).
    for d in spec.get("dashboards", []):
        if "rows" in d:
            cells = [c if isinstance(c, str) else c["sheet"] for row in d["rows"] for c in row["cells"]]
            d["layout"] = [cells]
    return spec


# ---------------------------------------------------------------- decorate (after build)
def run(text: str, size: int, fg: str, font: str = "Tableau Book") -> str:
    return f"<run fontcolor='{fg}' fontname='{font}' fontsize='{size}'>{text}</run>"


def fld(token: str) -> str:
    return f"<![CDATA[<{token}>]]>"


def _ws_span(xml: str, name: str) -> tuple[int, int]:
    for q in (quoteattr(name), "'" + escape(name).replace("'", "&apos;") + "'"):
        i = xml.find(f"<worksheet name={q}>")
        if i >= 0:
            return i, xml.index("</worksheet>", i) + len("</worksheet>")
    raise KeyError(name)


def _tokens(ws_xml: str) -> dict[str, str]:
    """column id -> full shelf token, from the sheet's column-instances."""
    ds = re.search(r"<datasource-dependencies datasource='([^']+)'>(?:(?!</datasource-dependencies>).)*column-instance", ws_xml, re.S)
    out = {}
    for block in re.finditer(r"<datasource-dependencies datasource='([^']+)'>(.*?)</datasource-dependencies>", ws_xml, re.S):
        for m in re.finditer(r"<column-instance column=[\"']\[([^\]]+)\][\"'][^>]*name=[\"'](\[[^\"']+\])[\"']", block.group(2)):
            out[m.group(1)] = f"[{block.group(1)}].{m.group(2)}"
    return out if ds or out else {}


def _primary_ds(ws_xml: str) -> str:
    """The sheet's own datasource name (the Parameters block can come first)."""
    return next(m.group(1) for m in re.finditer(r"<datasource-dependencies datasource='([^']+)'", ws_xml) if m.group(1) != "Parameters")


def _set_style(ws_xml: str, style: str) -> str:
    return re.sub(r"(</view>\s*)(<style>.*?</style>|<style />)", lambda m: m.group(1) + style, ws_xml, count=1, flags=re.S)


def _chrome(t: dict, axis: str = "", label: str = "", grid_rows: bool = False) -> str:
    grid = (f"<format attr='stroke-color' scope='rows' value='{t['grid']}' />" if grid_rows
            else "<format attr='line-visibility' scope='rows' value='off' />")
    return ("<style>"
            f"<style-rule element='worksheet'><format attr='font-family' value='{t['font']}' /><format attr='color' value='{t['ink2']}' />"
            "<format attr='display-field-labels' scope='rows' value='false' /><format attr='display-field-labels' scope='cols' value='false' /></style-rule>"
            f"<style-rule element='gridline'>{grid}<format attr='line-visibility' scope='cols' value='off' /></style-rule>"
            "<style-rule element='zeroline'><format attr='line-visibility' scope='rows' value='off' /><format attr='line-visibility' scope='cols' value='off' /></style-rule>"
            "<style-rule element='axis'><format attr='line-visibility' scope='rows' value='off' /><format attr='line-visibility' scope='cols' value='off' />"
            f"<format attr='color' value='{t['ink3']}' /><format attr='font-size' value='9' />{axis}</style-rule>"
            "<style-rule element='table-div'><format attr='line-visibility' scope='rows' value='off' /><format attr='line-visibility' scope='cols' value='off' /></style-rule>"
            f"<style-rule element='header'><format attr='color' value='{t['ink3']}' /><format attr='font-size' value='9' /></style-rule>"
            f"<style-rule element='label'><format attr='color' value='{t['ink3']}' /><format attr='font-size' value='9' />{label}</style-rule>"
            f"<style-rule element='table'><format attr='background-color' value='{t['card']}' /></style-rule>"
            "</style>")


def _title(t: dict, text: str, legend: list | None, spec: dict) -> str:
    runs = run(escape(text), 12, t["ink"], t["semi"])
    for item in legend or []:
        label, col = (item if isinstance(item, (list, tuple)) else (item, "accent"))
        runs += run("     ●", 11, color(spec, col)) + run(" " + escape(label), 10, t["ink2"])
    return f"<layout-options><title><formatted-text>{runs}</formatted-text></title></layout-options>"


def _retitle(w: str, t: dict, text: str, legend, spec) -> str:
    w = re.sub(r"<layout-options>.*?</layout-options>", "", w, flags=re.S)
    return re.sub(r"(<worksheet name=[^>]+>)", lambda m: m.group(1) + _title(t, text, legend, spec), w, count=1)


def _horizontal_months(w: str) -> str:
    cols = re.search(r"<cols>(.*?)</cols>", w, re.S)
    if not cols or not cols.group(1).strip():
        return w
    tok = cols.group(1).strip().split(" / ")[0].replace("&amp;", "&")
    return w.replace("<style-rule element='header'>", f"<style-rule element='header'><format attr='text-orientation' field={quoteattr(tok)} value='0' />", 1)


def decorate(xml: str, spec: dict, calc_ids: dict) -> str:
    """Apply the theme and component styling to every worksheet that came from expand()."""
    if not spec.get("theme"):
        return xml
    t = theme(spec)
    palettes: dict[str, list] = {}
    for ws in spec.get("worksheets", []):
        d = ws.get("_design")
        if not d:
            continue
        a, b = _ws_span(xml, ws["name"])
        w = xml[a:b]
        ds_alias = ws.get("datasource") or spec["datasources"][0]["alias"]
        ids = calc_ids.get(ds_alias, {})
        toks = _tokens(w)
        tok = lambda n: toks.get(ids.get(n, ""), "")  # noqa: E731
        kind = d["kind"]
        if kind == "card":
            w = _card(w, t, d, tok, spec)
        elif kind == "combo":
            w = _combo(w, t, d, tok, spec, ws)
        elif kind in ("ranked_bars", "chart"):
            axis = ""
            if kind == "ranked_bars" or d.get("direct_labels"):
                for shelf, scope in (("cols", "cols"), ("rows", "rows")):
                    for tk in re.findall(r"\[[^\]]+\]\.\[(?:usr|sum|avg|min|max|cnt|ctd|med):[^\]]+\]", re.search(rf"<{shelf}>(.*?)</{shelf}>", w, re.S).group(1)):
                        axis += f"<format attr='display' class='0' field={quoteattr(tk)} scope='{scope}' value='false' />"
            mark_color = color(spec, d.get("color")) if kind == "ranked_bars" else None
            if mark_color:
                w = re.sub(r"<mark class='Bar' />", f"<mark class='Bar' /><style><style-rule element='mark'><format attr='mark-color' value='{mark_color}' />"
                           "<format attr='mark-labels-show' value='true' /><format attr='size' value='0.65' /></style-rule></style>", w, count=1)
            w = _set_style(w, _chrome(t, axis, grid_rows=not axis))
            w = _horizontal_months(w)
            w = _retitle(w, t, ws.get("title") or ws["name"], d.get("legend"), spec)
        elif kind == "status_bars":
            ds_name = _primary_ds(w)
            palettes.setdefault(ds_name, []).extend((f"[{ds_name}].[usr:{ids[n]}:qk]", color(spec, c)) for n, c in d["bands"])
            w = w.replace("<aggregation value='true' />", f"<filter class='quantitative' column={quoteattr(tok(d['value']) or '')} included-values='non-null' /><aggregation value='true' />", 1) if tok(d["value"]) else w
            w = _set_style(w, _chrome(t, f"<format attr='display' class='0' field='[{ds_name}].[Multiple Values]' scope='cols' value='false' />",
                                      f"<format attr='display' field='[{ds_name}].[:Measure Names]' value='false' />"))
            w = w.replace("<style-rule element='table'>", f"<style-rule element='datalabel'><format attr='color' value='#FFFFFF' /><format attr='font-family' value='{t['semi']}' /></style-rule><style-rule element='table'>", 1)
            w = re.sub(r"<mark class='Bar' />", "<mark class='Bar' /><style><style-rule element='mark'><format attr='mark-labels-show' value='true' /><format attr='size' value='0.65' /></style-rule></style>", w, count=1)
            w = _retitle(w, t, ws.get("title") or ws["name"], [(n, c) for n, c in d["bands"]], spec)
        elif kind == "table":
            w = _table(w, t, d, spec, ws)
        xml = xml[:a] + w + xml[b:]
    for ds_name, maps in palettes.items():
        body = "".join(f"<map to='{c}'><bucket>{escape(json.dumps(k))}</bucket></map>" for k, c in maps)
        pal = f"<style><style-rule element='mark'><encoding attr='color' field='[:Measure Names]' type='palette'>{body}</encoding></style-rule></style>"
        xml = re.sub(rf"(<datasource caption=[^>]*name='{re.escape(ds_name)}'.*?)(</datasource>)", lambda m: m.group(1) + pal + m.group(2), xml, count=1, flags=re.S)
    return xml


def _card(w: str, t: dict, d: dict, tok, spec) -> str:
    runs = [run(escape(d["label"]) + (" · " if d.get("label_field") else ""), 9, t["ink3"], t["semi"])]
    if d.get("label_field"):
        runs.append(run(fld(tok(d["label_field"])), 9, t["ink3"], t["semi"]))
    runs += [run("Æ&#10;", 9, t["ink2"], t["font"]), run(fld(tok(d["value"])), 26, t["ink"], t["semi"]), run("Æ&#10;", 4, t["ink2"], t["font"])]
    cmp = d.get("compare")
    if cmp:
        vs = cmp["text"] + (" " + fld(tok(cmp["text_field"])) if cmp.get("text_field") else "") + "  " + fld(tok(cmp["previous"]))
        runs += [run(fld(tok(cmp["up"])), 10, t["good"], t["semi"]), run(fld(tok(cmp["down"])), 10, t["bad"], t["semi"]),
                 run(" " + vs, 10, t["ink3"], t["font"])]
    sec = d.get("secondary")
    if sec:
        runs += [run("Æ&#10;", 10, t["ink2"], t["font"]), run(escape(sec["label"]) + "  ", 8, t["ink3"], t["semi"]),
                 run(fld(tok(sec["value"])), 12, t["ink"], t["semi"])]
        if sec.get("compare"):
            runs += [run(fld(tok(sec["compare"]["up"])), 10, t["good"], t["semi"]), run(fld(tok(sec["compare"]["down"])), 10, t["bad"], t["semi"])]
    if d.get("note"):
        runs += [run("Æ&#10;", 8, t["ink2"], t["font"]), run(escape(d["note"]), 8, t["ink3"], t["font"])]
    label = "<customized-label><formatted-text>" + "".join(runs) + "</formatted-text></customized-label>"
    w = re.sub(r"<customized-label>.*?</customized-label>", "", w, flags=re.S)
    w = w.replace("</encodings>", "</encodings>" + label, 1)
    w = w.replace("<mark class='Text' />", "<mark class='Text' /><style><style-rule element='mark'><format attr='mark-labels-show' value='true' />"
                  "<format attr='mark-labels-cull' value='false' /></style-rule></style>", 1)
    return _set_style(w, "<style><style-rule element='cell'><format attr='text-align' value='left' /><format attr='vertical-align' value='top' /></style-rule>"
                         f"<style-rule element='table'><format attr='background-color' value='{t['card']}' /></style-rule></style>")


def _combo(w: str, t: dict, d: dict, tok, spec, ws) -> str:
    t1, t2 = tok(d["first"]), tok(d["second"])
    w = re.sub(r"<rows>.*?</rows>", f"<rows>({escape(t1)} + {escape(t2)})</rows>", w, count=1, flags=re.S)
    m1, m2 = (m.title() for m in d["marks"])
    c1, c2 = color(spec, d["colors"][0]), color(spec, d["colors"][1], "reference")
    lab_enc, lab_style = "", ""
    if d.get("label"):
        lab_enc = f"<encodings><text column={quoteattr(tok(d['label']))} /></encodings>"
        lab_style = "<format attr='mark-labels-show' value='true' /><format attr='mark-labels-cull' value='true' />"
    size1 = "<format attr='size' value='0.6' />" if m1 == "Bar" else "<format attr='size' value='1.6' /><format attr='mark-markers-mode' value='all' />"
    panes = ("<panes><pane selection-relaxation-option='selection-relaxation-allow'><view><breakdown value='auto' /></view><mark class='Automatic' /></pane>"
             f"<pane id='1' selection-relaxation-option='selection-relaxation-allow' y-axis-name={quoteattr(t1)}><view><breakdown value='auto' /></view>"
             f"<mark class='{m1}' />{lab_enc}<style><style-rule element='mark'><format attr='mark-color' value='{c1}' />{lab_style}{size1}</style-rule></style></pane>"
             f"<pane id='2' selection-relaxation-option='selection-relaxation-allow' y-axis-name={quoteattr(t2)}><view><breakdown value='auto' /></view>"
             f"<mark class='{m2}' /><style><style-rule element='mark'><format attr='mark-color' value='{c2}' /><format attr='mark-markers-mode' value='all' />"
             "<format attr='size' value='1.2' /></style-rule></style></pane></panes>")
    w = re.sub(r"<panes>.*?</panes>", panes, w, count=1, flags=re.S)
    rng = ""
    if d.get("range"):
        lo, hi = d["range"]
        rng = f"<encoding attr='space' class='0' field={quoteattr(t1)} field-type='quantitative' max='{hi}' min='{lo}' range-type='fixed' scope='rows' type='space' />"
    axis = (rng + f"<encoding attr='space' class='0' field={quoteattr(t2)} field-type='quantitative' fold='true' scope='rows' synchronized='true' type='space' />"
            f"<format attr='display' class='0' field={quoteattr(t1)} scope='rows' value='false' />"
            f"<format attr='display' class='0' field={quoteattr(t2)} scope='rows' value='false' />")
    w = _set_style(w, _chrome(t, axis))
    w = _horizontal_months(w)
    legend = d.get("legend")
    if legend and not isinstance(legend[0], (list, tuple)):
        legend = list(zip(legend, d["colors"]))
    return _retitle(w, t, ws.get("title") or ws["name"], legend, spec)


def _table(w: str, t: dict, d: dict, spec, ws) -> str:
    ds_name = _primary_ds(w)
    labels = ""
    for f in d["row_fields"]:
        ftok = f"[{ds_name}].[none:{f}:nk]"
        labels += (f"<format attr='color' field={quoteattr(ftok)} value='{t['ink']}' /><format attr='font-size' field={quoteattr(ftok)} value='11' />"
                   f"<format attr='text-align' field={quoteattr(ftok)} value='left' />")
    style = ("<style>"
             f"<style-rule element='worksheet'><format attr='font-family' value='{t['font']}' /><format attr='color' value='{t['ink']}' />"
             "<format attr='display-field-labels' scope='rows' value='false' /><format attr='display-field-labels' scope='cols' value='false' /></style-rule>"
             f"<style-rule element='table'><format attr='background-color' value='{t['card']}' /><format attr='band-size' scope='rows' value='1' />"
             "<format attr='band-level' scope='rows' value='1' /></style-rule>"
             f"<style-rule element='pane'><format attr='band-color' scope='rows' value='{t['band']}' /></style-rule>"
             "<style-rule element='table-div'><format attr='line-visibility' scope='rows' value='off' /><format attr='line-visibility' scope='cols' value='off' /></style-rule>"
             "<style-rule element='gridline'><format attr='line-visibility' scope='rows' value='off' /><format attr='line-visibility' scope='cols' value='off' /></style-rule>"
             f"<style-rule element='cell'><format attr='text-align' value='right' /><format attr='font-size' value='11' /><format attr='color' value='{t['ink']}' /></style-rule>"
             f"<style-rule element='label'><format attr='font-size' value='9' /><format attr='color' value='{t['ink3']}' />{labels}</style-rule>"
             "</style>")
    w = _set_style(w, style)
    return _retitle(w, t, ws.get("title") or ws["name"], None, spec)
