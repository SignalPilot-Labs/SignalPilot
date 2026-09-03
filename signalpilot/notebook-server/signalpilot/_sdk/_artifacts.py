"""Artifact paths and the house chart theme for chat notebooks.

A file saved under the artifacts directory is captured by the chat runtime.
No publish call is necessary.
"""

from __future__ import annotations

import os
from pathlib import Path, PurePosixPath

CHART_BACKGROUND = "#141416"
CHART_TEXT = "#EDEDED"
CHART_AXIS = "#55555C"
CHART_GRID = "#333338"
# Okabe-Ito palette. Distinguishable for common color vision deficiencies.
CHART_COLORS = (
    "#56B4E9",
    "#E69F00",
    "#009E73",
    "#F0E442",
    "#0072B2",
    "#D55E00",
    "#CC79A7",
    "#B3B3B3",
)
CHART_FONT_FAMILY = "DM Sans"


def artifacts_directory() -> Path:
    """Resolve the artifacts directory for the current process."""
    explicit = os.getenv("SP_CHAT_ARTIFACTS_DIRECTORY", "").strip()
    if explicit:
        return Path(explicit)
    scratch = os.getenv("SP_CHAT_SCRATCH_DIRECTORY", "").strip()
    if scratch:
        return Path(scratch) / "artifacts"
    return Path("artifacts")


def _validate_name(name: str) -> PurePosixPath:
    text = str(name or "").strip().replace("\\", "/")
    if not text:
        raise ValueError("artifact name must not be empty")
    if text.startswith("/"):
        raise ValueError("artifact name must be relative")
    # Split by hand. PurePosixPath drops "." segments, and those are
    # rejected on purpose.
    for segment in text.split("/"):
        if segment in {"", ".", ".."} or segment.startswith("."):
            raise ValueError(
                "artifact name must not contain '..' or dot segments"
            )
    return PurePosixPath(text)


def artifact_path(name: str) -> Path:
    """Return the path for one artifact file and create its directory.

    `name` is a file name or a relative path with no `..`, no leading `/`,
    and no dot segment. The chat shows the file in the Artifacts panel as
    soon as it is saved.
    """
    relative = _validate_name(name)
    destination = artifacts_directory() / Path(*relative.parts)
    destination.parent.mkdir(parents=True, exist_ok=True)
    return destination


def matplotlib_rc_params() -> dict[str, object]:
    """The house theme as matplotlib rcParams. Pure data."""
    return {
        "figure.facecolor": CHART_BACKGROUND,
        "savefig.facecolor": CHART_BACKGROUND,
        "axes.facecolor": CHART_BACKGROUND,
        "text.color": CHART_TEXT,
        "axes.labelcolor": CHART_TEXT,
        "xtick.color": CHART_TEXT,
        "ytick.color": CHART_TEXT,
        "axes.edgecolor": CHART_AXIS,
        "grid.color": CHART_GRID,
        "axes.grid": True,
        "axes.spines.top": False,
        "axes.spines.right": False,
        "figure.figsize": (10, 5.6),
        "figure.dpi": 200,
        "savefig.dpi": 200,
        "savefig.bbox": "tight",
        "savefig.pad_inches": 0.3,
        "font.family": "sans-serif",
        "font.sans-serif": [
            CHART_FONT_FAMILY,
            "DejaVu Sans",
            "Arial",
            "Helvetica",
            "sans-serif",
        ],
        "axes.titleweight": 600,
        "legend.frameon": False,
    }


def _apply_matplotlib_theme() -> bool:
    try:
        import matplotlib as mpl
    except ImportError:
        return False
    params = dict(matplotlib_rc_params())
    params["axes.prop_cycle"] = mpl.cycler(color=list(CHART_COLORS))
    mpl.rcParams.update(params)
    return True


def _apply_plotly_theme() -> bool:
    try:
        import plotly.graph_objects as go
        import plotly.io as pio
    except ImportError:
        return False
    axis = {
        "gridcolor": CHART_GRID,
        "linecolor": CHART_AXIS,
        "zerolinecolor": CHART_GRID,
        "tickcolor": CHART_TEXT,
    }
    template = go.layout.Template(
        layout={
            "paper_bgcolor": CHART_BACKGROUND,
            "plot_bgcolor": CHART_BACKGROUND,
            "font": {
                "color": CHART_TEXT,
                "family": f"{CHART_FONT_FAMILY}, sans-serif",
            },
            "colorway": list(CHART_COLORS),
            "xaxis": dict(axis),
            "yaxis": dict(axis),
            "legend": {"bgcolor": "rgba(0,0,0,0)"},
        }
    )
    pio.templates["signalpilot"] = template
    pio.templates.default = "signalpilot"
    return True


def apply_chart_theme() -> None:
    """Apply the SignalPilot matplotlib rcParams and Plotly template.

    A missing plotting library is not an error.
    """
    try:
        _apply_matplotlib_theme()
    except Exception:
        pass
    try:
        _apply_plotly_theme()
    except Exception:
        pass
