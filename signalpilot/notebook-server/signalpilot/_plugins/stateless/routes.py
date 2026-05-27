# Copyright 2026 SignalPilot. All rights reserved.
from __future__ import annotations

from typing import TYPE_CHECKING, Any, Final

from signalpilot._output.formatting import as_html
from signalpilot._output.hypertext import Html
from signalpilot._output.rich_help import mddoc
from signalpilot._plugins.stateless import lazy
from signalpilot._plugins.ui._core.ui_element import UIElement

if TYPE_CHECKING:
    from collections.abc import Callable, Coroutine


@mddoc
class routes(UIElement[str, str]):
    """Renders a list of routes that are switched based on the URL path.

    Routes currently don't support nested routes, or dynamic routes (e.g. `#/user/:id`).
    If you'd like to see these features, please let us know on GitHub:
    https://docs.signalpilot.ai/docs/

    For a simple-page-application (SPA) experience, you should use hash-based routing.
    For example, prefix your routes with `#/`.

    If you are using a multi-page-application (MPA) with `sp.create_asgi_app`,
    you should use path-based routing. For example, prefix your routes with `/`.

    Examples:
        ```python
        sp.routes(
            {
                "#/": render_home,
                "#/about": render_about,
                "#/contact": render_contact,
                sp.routes.CATCH_ALL: render_home,
            }
        )
        ```

    Args:
        routes (dict[str, Union[Callable[[], object], Callable[[], Coroutine[None, None, object]], object]]):
            A dictionary of routes, where the key is the URL path and the value is a function
            that returns the content to display.

    Returns:
        Html (sp.Html): An Html object.
    """

    _name: Final[str] = "sp-routes"

    CATCH_ALL = "{/*path}"
    DEFAULT = "/"

    def __init__(
        self,
        routes: dict[
            str,
            Callable[[], object]
            | Callable[[], Coroutine[None, None, object]]
            | object,
        ],
    ) -> None:
        # For functions, wrap in lazy
        children: list[Html] = []
        for content in routes.values():
            if callable(content):
                children.append(lazy.lazy(content))
            else:
                children.append(as_html(content))

        self._children = children
        text = "".join([child.text for child in children])

        super().__init__(
            component_name=self._name,
            initial_value="",
            label=None,
            args={
                "routes": list(routes.keys()),
            },
            on_change=None,
            slotted_html=text,
        )

    def _convert_value(self, value: str) -> str:
        return value

    # Not supported
    def batch(self, *args: Any, **kwargs: Any) -> Any:
        del args, kwargs
        raise TypeError(".batch() is not supported on sp.sidebar")

    def center(self, *args: Any, **kwargs: Any) -> Html:
        del args, kwargs
        raise TypeError(".center() is not supported on sp.sidebar")

    def right(self, *args: Any, **kwargs: Any) -> Html:
        del args, kwargs
        raise TypeError(".right() is not supported on sp.sidebar")

    def left(self, *args: Any, **kwargs: Any) -> Html:
        del args, kwargs
        raise TypeError(".left() is not supported on sp.sidebar")

    def callout(self, *args: Any, **kwargs: Any) -> Html:
        del args, kwargs
        raise TypeError(".callout() is not supported on sp.sidebar")

    def style(self, *args: Any, **kwargs: Any) -> Html:
        del args, kwargs
        raise TypeError(".style() is not supported on sp.sidebar")
