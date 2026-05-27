# Copyright 2026 SignalPilot. All rights reserved.
from __future__ import annotations

from typing import Literal

from signalpilot._output.formatting import as_html
from signalpilot._output.hypertext import Html
from signalpilot._output.rich_help import mddoc
from signalpilot._plugins.core.web_component import build_stateless_plugin


@mddoc
def callout(
    value: object,
    kind: Literal["neutral", "warn", "success", "info", "danger"] = "neutral",
) -> Html:
    """Build a callout output.

    Args:
        value: A value to render in the callout
        kind: The kind of callout (affects styling).

    Returns:
        Html (sp.Html): An HTML object.
    """
    return Html(
        build_stateless_plugin(
            component_name="sp-callout-output",
            args={"html": as_html(value).text, "kind": kind},
        )
    )
