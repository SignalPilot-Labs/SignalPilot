# Copyright 2026 SignalPilot. All rights reserved.
from __future__ import annotations

from typing import TYPE_CHECKING, Any

from signalpilot._output.formatters.structures import format_structure
from signalpilot._output.hypertext import Html
from signalpilot._output.rich_help import mddoc
from signalpilot._plugins.stateless.flex import hstack, vstack
from signalpilot._plugins.stateless.json_output import json_output
from signalpilot._plugins.ui._core.ui_element import UIElement
from signalpilot._plugins.ui._impl.batch import _batch_base, validate_and_clone

if TYPE_CHECKING:
    from collections.abc import Callable


@mddoc
class dictionary(_batch_base):
    """A dictionary of UI elements.

    Use a dictionary to:
    - create a set of UI elements at runtime
    - group together logically related UI elements
    - keep the number of global variables in your program small

    Access the values of the elements using the `value` attribute of the
    dictionary. The elements in the dictionary can be accessed using square brackets
    (`dictionary[key]`) and embedded in other sp outputs. You can also
    iterate over the UI elements using the same syntax used for Python dicts.

    Note:
        The UI elements in the dictionary are clones of the original
        elements: interacting with the dictionary will _not_ update the original
        elements, and vice versa.

        The main reason to use `sp.ui.dictionary` is for reactive execution — when you
        interact with an element in a `sp.ui.dictionary`, all cells that reference the
        `sp.ui.dictionary` run automatically, just like all other ui elements. When you
        use a regular dictionary, you don't get this reactivity.

    Examples:
        A heterogeneous collection of UI elements:
        ```python
        d = sp.ui.dictionary(
            {
                "slider": sp.ui.slider(1, 10),
                "text": sp.ui.text(),
                "date": sp.ui.date(),
            }
        )
        ```

        Get the values of the `slider`, `text`, and `date` elements via
        `d.value`:
        ```python
        # d.value returns a dict with keys "slider", "text", "date"
        d.value
        ```

        Access and output a UI element in the array:
        ```python
        sp.md(f"This is a slider: {d['slider']}")
        ```

        Some number of UI elements, determined at runtime:
        ```python
        sp.ui.dictionary(
            {
                f"option {i}": sp.ui.slider(1, 10)
                for i in range(random.randint(4, 8))
            }
        )
        ```

        Quick layouts of UI elements:
        ```python
        sp.ui.dictionary(
            {
                f"option {i}": sp.ui.slider(1, 10)
                for i in range(random.randint(4, 8))
            }
        ).vstack()  # Can also use `hstack`, `callout`, `center`, etc.
        ```

    Attributes:
        value (dict): A dict holding the values of the UI elements, keyed by
            their names.
        elements (dict): A dict of the wrapped elements (clones of the originals).
        on_change (Optional[Callable[[dict[str, object]], None]]): Optional callback
            to run when this element's value changes.

    Args:
        elements (dict[str, UIElement[Any, Any]]): A dict mapping names to UI
            elements to include.
        label (str, optional): A descriptive name for the dictionary. Defaults to "".
        on_change (Callable[[dict[str, object]], None], optional): Optional callback
            to run when this element's value changes.
    """

    def __init__(
        self,
        elements: dict[str, UIElement[Any, Any]],
        *,
        label: str = "",
        on_change: Callable[[dict[str, object]], None] | None = None,
    ) -> None:
        # Why we clone the wrapped elements:
        #
        # We don't have good semantics for embedding the original
        # elements into the dictionary. Here are some complications
        # with doing that:
        #
        # 1. Interacting with an element in the dict might cause the cell
        # that created the dict to re-run (if the element were declared
        # in another cell), causing the dict to be destroyed and recreated
        # with a new object-id, which in turn will re-initialize the dict
        # and interrupt all interactivity
        #
        # 2. Interacting with the original element in another cell may
        # again cause the dict to be destroyed/recreated; moreover, the
        # interaction will not update the value of the dictionary (unless
        # additional logic were added to the frontend DictPlugin to spy on
        # signalpilotValueUpdateEvents of children), and in any case will not
        # trigger cells that ref the dictionary to run, leading to confusion
        elements = validate_and_clone(elements)

        self._label = label
        # slot a JSON tree viewer as the contents of this element
        slotted_html = json_output(
            json_data=format_structure(elements),
            name="dictionary" if not label else label,
        )
        super().__init__(
            html=slotted_html,
            elements=elements,
            label=label,
            on_change=on_change,
        )

    def _clone(self) -> dictionary:
        """Custom clone method so new dict gets copies of UI elements."""
        return dictionary(
            self.elements, label=self._label, on_change=self._on_change
        )

    def hstack(self, **kwargs: Any) -> Html:
        """
        Stack the elements horizontally.

        For kwargs, see `sp.hstack`.
        """
        return hstack(items=list(self.elements.values()), **kwargs)

    def vstack(self, **kwargs: Any) -> Html:
        """
        Stack the elements vertically.

        For kwargs, see `sp.vstack`.
        """
        return vstack(items=list(self.elements.values()), **kwargs)
