from __future__ import annotations

from signalpilot._output.formatting import as_html
from signalpilot._output.hypertext import Html
from signalpilot._output.rich_help import mddoc


@mddoc
def center(item: object) -> Html:
    """Center an item.

    Args:
        item: object to center.

    Returns:
        A centered `Html` object.
    """
    return as_html(item).center()


@mddoc
def left(item: object) -> Html:
    """Left-justify an item.

    Args:
        item: object to left-justify.

    Returns:
        A left-justified `Html` object.
    """
    return as_html(item).left()


@mddoc
def right(item: object) -> Html:
    """Right-justify an item.

    Args:
        item: object to right-justify.

    Returns:
        A right-justified `Html` object.
    """
    return as_html(item).right()
