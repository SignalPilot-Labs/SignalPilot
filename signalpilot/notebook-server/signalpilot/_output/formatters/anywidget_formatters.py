from __future__ import annotations

from signalpilot._messaging.mimetypes import KnownMimeType
from signalpilot._output.formatters.formatter_factory import FormatterFactory
from signalpilot._plugins.ui._impl.from_anywidget import from_anywidget


class AnyWidgetFormatter(FormatterFactory):
    @staticmethod
    def package_name() -> str:
        return "anywidget"

    def register(self) -> None:
        import anywidget  # type: ignore [import-not-found]

        from signalpilot._output import formatting
        from signalpilot._plugins.ui._impl.anywidget.comm_provider import (
            patch_comm_create,
        )

        # Patch the comm library so anywidget's descriptor API
        # (MimeBundleDescriptor) creates comms that work in sp.
        patch_comm_create()

        @formatting.formatter(anywidget.AnyWidget)
        def _from(lmap: anywidget.AnyWidget) -> tuple[KnownMimeType, str]:
            return from_anywidget(lmap)._mime_()
