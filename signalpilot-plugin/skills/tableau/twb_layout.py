"""Floating card-grid dashboard layout for twb_build.py (used when a dashboard has "rows").

Dashboard spec:
    {"name": "Team Financial Scorecard", "width": 1600,
     "header": {"title": "Team Financial Scorecard", "subtitle": "gross margin and plan, month and YTD",
                "subtitle_param": "Sales Manager", "controls": ["Sales Manager", "Report Month"]},
     "rows": [{"height": 158, "cells": ["Card A", "Card B", "Card C"]},
              {"height": 356, "cells": [{"sheet": "Chart A", "width": 0.44}, {"sheet": "Chart B", "width": 0.56}]}],
     "footer": "Definitions: ..."}

Every panel is a white rounded card on a gray canvas with 12 px gutters. Card sheets hide their title.
Tableau floating layout: one tiled root zone (it carries the canvas color), then every object as a sibling.
"""

from __future__ import annotations

import re
from xml.sax.saxutils import escape, quoteattr

import twb_design as D

GUTTER, HEADER, FOOTER = 12, 84, 44


def height(d: dict) -> int:
    h = GUTTER + (HEADER + GUTTER if d.get("header") else 0)
    h += sum(r["height"] + GUTTER for r in d["rows"])
    return h + (FOOTER + GUTTER if d.get("footer") else 0)


def prepare(spec: dict) -> None:
    for d in spec.get("dashboards", []):
        if "rows" in d:
            d.setdefault("width", 1600)
            d["height"] = height(d)


def _zs(t: dict, bg: str | None, padding: int, radius: int = 10) -> str:
    return ("<zone-style><format attr='border-style' value='none' /><format attr='border-width' value='0' /><format attr='margin' value='0' />"
            f"<format attr='padding' value='{padding}' />" + (f"<format attr='background-color' value='{bg}' />" if bg else "")
            + (f"<format attr='corner-radius' value='{radius}' />" if bg == t["card"] and radius else "") + "</zone-style>")


def apply(xml: str, spec: dict, params: dict) -> str:
    t = D.theme(spec)
    cards = {w["name"] for w in spec["worksheets"] if (w.get("_design") or {}).get("kind") == "card"}
    for d in spec.get("dashboards", []):
        if "rows" not in d:
            continue
        W, H = d["width"], d["height"]
        ids = iter(range(100, 10000))
        X = lambda v: int(round(v / W * 100000))  # noqa: E731
        Y = lambda v: int(round(v / H * 100000))  # noqa: E731

        def zone(x, y, w, h, body="", **a):
            attrs = "".join(f" {k.replace('_', '-')}={quoteattr(str(v))}" for k, v in a.items())
            return f"<zone h='{Y(h)}' id='{next(ids)}'{attrs} w='{X(w)}' x='{X(x)}' y='{Y(y)}'>{body}</zone>"

        g, z, y = GUTTER, [], GUTTER
        hd = d.get("header")
        if hd:
            ctrls = [c for c in hd.get("controls", []) if c in params]
            cw = 260
            text = D.run(escape(hd.get("title", d["name"])), 18, t["ink"], t["semi"]) + D.run("Æ&#10;", 4, t["ink2"], t["font"])
            if hd.get("subtitle_param") in params:
                text += D.run(D.fld(f"[Parameters].{params[hd['subtitle_param']]['id']}"), 10, t["accent"], t["semi"])
                text += D.run("  ·  ", 10, t["ink3"], t["font"])
            text += D.run(escape(hd.get("subtitle", "")), 10, t["ink3"], t["font"])
            z.append(zone(g, y, W - 2 * g, HEADER, _zs(t, t["card"], 0), type_v2="empty"))
            z.append(zone(g, y, W - 2 * g - cw * len(ctrls), HEADER, f"<formatted-text>{text}</formatted-text>" + _zs(t, None, 12), type_v2="text"))
            for i, c in enumerate(ctrls):
                x = W - g - cw * (len(ctrls) - i)
                z.append(zone(x, y + 10, cw - 6, HEADER - 20, _zs(t, None, 6), mode="compact",
                              param=f"[Parameters].{params[c]['id']}", type_v2="paramctrl"))
            y += HEADER + g
        for row in d["rows"]:
            cells = [c if isinstance(c, dict) else {"sheet": c} for c in row["cells"]]
            weights = [c.get("width", 1) for c in cells]
            avail = W - g * (len(cells) + 1)
            x = g
            for c, wt in zip(cells, weights):
                cw = avail * wt / sum(weights)
                extra = {"show_title": "false"} if c["sheet"] in cards or c.get("title") is False else {}
                z.append(zone(x, y, cw, row["height"], _zs(t, t["card"], 12 if c["sheet"] in cards else 14), name=c["sheet"], **extra))
                x += cw + g
            y += row["height"] + g
        if d.get("footer"):
            text = D.run("Definitions  ", 9, t["ink2"], t["semi"]) + D.run(escape(d["footer"]), 9, t["ink3"], t["font"])
            z.append(zone(g, y, W - 2 * g, FOOTER, f"<formatted-text>{text}</formatted-text>" + _zs(t, t["card"], 10), type_v2="text"))
        root = ("<zones><zone h='100000' id='1' type-v2='layout-basic' w='100000' x='0' y='0'>"
                "<zone h='100000' id='2' param='vert' type-v2='layout-flow' w='100000' x='0' y='0'>"
                "<zone h='100000' id='3' type-v2='layout-basic' w='100000' x='0' y='0' /></zone>"
                f"{_zs(t, t['canvas'], 0)}</zone>" + "".join(z) + "</zones>")
        xml = re.sub(rf"(<dashboard name=[\"']{re.escape(escape(d['name']))}[\"']>.*?)<zones>.*?</zones>",
                     lambda m: m.group(1) + root, xml, count=1, flags=re.S)
    return xml
