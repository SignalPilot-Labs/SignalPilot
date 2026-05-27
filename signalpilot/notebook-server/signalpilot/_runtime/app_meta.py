# Copyright 2026 SignalPilot. All rights reserved.
from __future__ import annotations

from signalpilot._config.config import DEFAULT_CONFIG
from signalpilot._output.rich_help import mddoc
from signalpilot._runtime.commands import HTTPRequest
from signalpilot._runtime.context.types import (
    ContextNotInitializedError,
    get_context,
)
from signalpilot._runtime.context.utils import RunMode, get_mode


@mddoc
class AppMeta:
    """Metadata about the app.

    This class provides access to runtime metadata about a sp app, such as
    its display theme and execution mode.
    """

    @property
    def theme(self) -> str:
        """The display theme of the app.

        Returns:
            str: Either "light" or "dark". If the user's configuration is set to
                "system", currently returns "light".

        Examples:
            Get the current theme and conditionally set a plotting library's theme:

            ```python
            import altair as alt

            # Enable dark theme for Altair when sp is in dark mode
            alt.themes.enable(
                "dark" if sp.app_meta().theme == "dark" else "default"
            )
            ```
        """
        try:
            context = get_context()
            signalpilot_config = context.signalpilot_config
        except ContextNotInitializedError:
            signalpilot_config = DEFAULT_CONFIG

        theme = signalpilot_config["display"]["theme"] or "light"
        if theme == "system":
            # TODO(mscolnick): have frontend tell the backend the system theme
            return "light"
        return theme

    @property
    def mode(self) -> RunMode | None:
        """
        The execution mode of the app.

        Examples:
            Show content only in edit mode:

            ```python
            # Only show this content when editing the notebook
            sp.md(
                "# Developer Notes"
            ) if sp.app_meta().mode == "edit" else None
            ```

        Returns:
            - "edit": The notebook is being edited in the sp editor
            - "run": The notebook is being run as an app
            - "script": The notebook is being run as a script
            - "test": The cell has been invoked by a test
            - None: The mode could not be determined
        """
        return get_mode()

    @property
    def request(self) -> HTTPRequest | None:
        """
        The current HTTP request if any. The shape of the request object depends on the ASGI framework used,
        but typically includes:

        - `headers`: Request headers
        - `cookies`: Request cookies
        - `query_params`: Query parameters
        - `path_params`: Path parameters
        - `user`: User data added by authentication middleware
        - `url`: URL information including path, query parameters

        Examples:
            Get the current request and print the path:

            ```python
            request = sp.app_meta().request
            user = request.user
            print(
                user["is_authenticated"], user["username"], request.url["path"]
            )
            ```

        Returns:
            Optional[HTTPRequest]: The current request object if available, None otherwise.
        """
        try:
            context = get_context()
            return context.request
        except ContextNotInitializedError:
            return None
