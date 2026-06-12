from __future__ import annotations

from signalpilot._output.hypertext import Html
from signalpilot._output.rich_help import mddoc
from signalpilot._plugins.ui._impl.tabs import tabs as tabs_impl
from signalpilot._utils.deprecated import deprecated


@mddoc
@deprecated("sp.tabs is deprecated. Use sp.ui.tabs instead")
def tabs(tabs: dict[str, object]) -> Html:
    """Deprecated: Use `sp.ui.tabs` instead.

    Tabs of UI elements.

    Args:
        tabs: a dictionary of tab names to tab content; strings are interpreted
            as markdown

    Returns:
        An `Html` object.

    Example:
        ```python
        tab1 = sp.vstack([sp.ui.slider(1, 10), sp.ui.text(), sp.ui.date()])
        tab2 = sp.vstack(
            [
                {
                    "slider": sp.ui.slider(1, 10),
                    "text": sp.ui.text(),
                    "date": sp.ui.date(),
                }
            ]
        )
        tabs = sp.tabs({"Tab 1": tab1, "Tab 2": tab2})
        ```
    """
    return tabs_impl(tabs)
