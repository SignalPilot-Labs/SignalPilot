# Copyright 2026 SignalPilot. All rights reserved.
from __future__ import annotations

from signalpilot._output.formatters.formatter_factory import FormatterFactory
from signalpilot._plugins.ui._impl.anywidget.init import init_signalpilot_widget


class IPyWidgetsFormatter(FormatterFactory):
    @staticmethod
    def package_name() -> str:
        return "ipywidgets"

    def register(self) -> None:
        import ipywidgets  # type:ignore

        Widget = ipywidgets.Widget
        Widget.on_widget_constructed(init_signalpilot_widget)  # type:ignore
