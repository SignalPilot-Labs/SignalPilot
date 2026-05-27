# Copyright 2026 SignalPilot. All rights reserved.
from __future__ import annotations

from signalpilot._output.formatting import as_html
from signalpilot._output.hypertext import Html
from signalpilot._output.md import md
from signalpilot._output.rich_help import mddoc
from signalpilot._plugins.core.web_component import build_stateless_plugin
from signalpilot._plugins.stateless.lazy import lazy as lazy_ui


@mddoc
def accordion(
    items: dict[str, object], multiple: bool = False, lazy: bool = False
) -> Html:
    """Accordion of one or more items.

    Args:
        items: a dictionary of item names to item content; strings are
            interpreted as markdown
        multiple: whether to allow multiple items to be open simultaneously
        lazy: a boolean, whether to lazily load the accordion content.
            This is a convenience that wraps each accordion in a `sp.lazy`
            component.

    Returns:
        An `Html` object.

    Example:
        ```python3
        sp.accordion(
            {"Tip": "Use accordions to let users reveal and hide content."}
        )
        ```

        Accordion content can be lazily loaded:

        ```python3
        sp.accordion({"View total": expensive_item}, lazy=True)
        ```

        where `expensive_item` is the item to render, or a callable that
        returns the item to render.
    """

    def render_content(tab: object) -> str:
        if lazy:
            return lazy_ui(tab).text
        if isinstance(tab, str):
            return md(tab).text
        return as_html(tab).text

    item_labels = [md(label).text for label in items]
    item_content = "".join(
        ["<div>" + render_content(item) + "</div>" for item in items.values()]
    )
    return Html(
        build_stateless_plugin(
            component_name="sp-accordion",
            args={"labels": item_labels, "multiple": multiple},
            slotted_html=item_content,
        )
    )
