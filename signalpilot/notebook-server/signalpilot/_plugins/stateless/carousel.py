from __future__ import annotations

from typing import TYPE_CHECKING

from signalpilot._output.formatting import as_html
from signalpilot._output.hypertext import Html
from signalpilot._output.md import md
from signalpilot._output.rich_help import mddoc
from signalpilot._plugins.core.web_component import build_stateless_plugin

if TYPE_CHECKING:
    from collections.abc import Sequence


@mddoc
def carousel(
    items: Sequence[object],
) -> Html:
    """Create a carousel of items.

    Args:
        items: A list of items.

    Returns:
        An `Html` object.

    Example:
        ```python3
        sp.carousel([sp.md("..."), sp.ui.text_area()])
        ```
    """
    item_content = "".join(
        [
            (md(item).text if isinstance(item, str) else as_html(item).text)
            for item in items
        ]
    )

    return Html(
        build_stateless_plugin(
            component_name="sp-carousel",
            args={},
            slotted_html=item_content,
        )
    )
