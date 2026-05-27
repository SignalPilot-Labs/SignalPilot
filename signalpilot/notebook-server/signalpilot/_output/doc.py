# Copyright 2026 SignalPilot. All rights reserved.
from __future__ import annotations

from typing import Any

from signalpilot._output.hypertext import Html
from signalpilot._output.md import md
from signalpilot._output.rich_help import mddoc
from signalpilot._utils.methods import getcallable


@mddoc
def doc(obj: Any) -> Html | None:
    """Get documentation about an object.

    If the object implements the `RichHelp` protocol, the documentation will be
    rendered as markdown.

    Args:
        obj: The object to get documentation about.

    Returns:
        Documentation as an `Html` object if the object implements `RichHelp`;
        otherwise, documentation is printed to console (and nothing is returned)
    """
    if rich_help := getcallable(obj, "_rich_help_"):
        msg = rich_help()
        return (
            md(msg) if msg is not None else md("No documentation available.")
        )
    help(obj)
    return None
