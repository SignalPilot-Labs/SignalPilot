from __future__ import annotations

import html

from signalpilot._output.builder import h
from signalpilot._output.hypertext import Html
from signalpilot._output.rich_help import mddoc


@mddoc
def plain_text(text: str) -> Html:
    """Text that's fixed-width, with spaces and newlines preserved.

    Args:
        text: text to output

    Returns:
        An `Html` object representing the text.
    """
    img = h.pre(child=html.escape(text), class_="text-xs")
    return Html(img)
