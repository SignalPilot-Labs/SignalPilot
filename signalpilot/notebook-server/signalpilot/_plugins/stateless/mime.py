from __future__ import annotations

from signalpilot._output.hypertext import Html
from signalpilot._plugins.core.web_component import JSONType, build_stateless_plugin


def mime_renderer(mime: str, data: JSONType) -> Html:
    """Build a mime renderer element.

    Args:
    -----
    mime: MIME type of the data
    data: data to display

    Returns:
    --------
    A string of HTML for a mime renderer element.
    """
    return Html(
        build_stateless_plugin(
            component_name="sp-mime-renderer",
            args=({"mime": mime, "data": data}),
        )
    )
