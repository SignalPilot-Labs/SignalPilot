from __future__ import annotations

from signalpilot._ast.cell import Cell
from signalpilot._messaging.mimetypes import KnownMimeType
from signalpilot._output import formatting
from signalpilot._output.formatters.formatter_factory import FormatterFactory


class CellFormatter(FormatterFactory):
    @staticmethod
    def package_name() -> None:
        return None

    def register(self) -> None:
        @formatting.formatter(Cell)
        def _format_cell(cell: Cell) -> tuple[KnownMimeType, str]:
            return cell._help()._mime_()
