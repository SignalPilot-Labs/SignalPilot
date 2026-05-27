# Copyright 2026 SignalPilot. All rights reserved.
from __future__ import annotations

from signalpilot._output.hypertext import Html
from signalpilot._output.rich_help import mddoc
from signalpilot._plugins.core.web_component import build_stateless_plugin


@mddoc
def outline(*, label: str = "") -> Html:
    """Display a table of contents outline showing all markdown headers in the notebook.

    The outline automatically extracts all markdown headers from executed cells
    and displays them in a hierarchical structure with clickable navigation.

    Examples:
        Basic outline:
        ```python
        sp.outline()
        ```

        With custom label:
        ```python
        sp.outline(label="Table of Contents")
        ```

    Args:
        label (str, optional): A descriptive label for the outline. Defaults to "".

    Returns:
        Html: An HTML object that renders the outline component.
    """
    return Html(
        build_stateless_plugin(
            component_name="sp-outline",
            args={"label": label},
        )
    )
