# Copyright 2026 SignalPilot. All rights reserved.
from __future__ import annotations

from signalpilot._output.formatters.formatter_factory import FormatterFactory
from signalpilot._runtime.context.utils import running_in_notebook


class PygWalkerFormatter(FormatterFactory):
    @staticmethod
    def package_name() -> str:
        return "pygwalker"

    def register(self) -> None:
        if running_in_notebook():
            # monkey-patch pygwalker.walk to work in sp;
            # older versions of sp may not have api.sp, and not sure
            # about pygwalker's API stability, so use a coarse try/except
            try:
                import pygwalker  # type: ignore
                from pygwalker.api.sp import walk  # type: ignore

                pygwalker.walk = walk  # type: ignore
            except Exception:
                pass
