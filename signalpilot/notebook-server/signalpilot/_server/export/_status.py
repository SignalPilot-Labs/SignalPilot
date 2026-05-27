from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import Literal

from signalpilot import _loggers

LOGGER = _loggers.sp_logger()

PDFExportPhase = Literal[
    "execute",
    "execute_complete",
    "raster",
    "prepare",
    "render",
    "render_fallback",
    "complete",
]


@dataclass(frozen=True)
class PDFExportStatusEvent:
    phase: PDFExportPhase
    message: str
    current: int | None = None
    total: int | None = None


PDFExportStatusCallback = Callable[[PDFExportStatusEvent], None]


def emit_pdf_export_status(
    status_callback: PDFExportStatusCallback | None,
    *,
    phase: PDFExportPhase,
    message: str,
    current: int | None = None,
    total: int | None = None,
) -> None:
    if status_callback is None:
        return

    try:
        status_callback(
            PDFExportStatusEvent(
                phase=phase,
                message=message,
                current=current,
                total=total,
            )
        )
    except Exception as e:
        LOGGER.debug("PDF export status callback failed: %s", e, exc_info=e)
