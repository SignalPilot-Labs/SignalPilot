"""Interactive UI elements.

This module contains a library of interactive UI elements.
"""

__all__ = [
    "altair_chart",
    "anywidget",
    "array",
    "batch",
    "button",
    "checkbox",
    "code_editor",
    "data_editor",
    "data_explorer",
    "dataframe",
    "date",
    "date_range",
    "datetime",
    "dictionary",
    "dropdown",
    "experimental_data_editor",
    "file",
    "file_browser",
    "form",
    "matplotlib",
    "matrix",
    "microphone",
    "multiselect",
    "number",
    "panel",
    "plotly",
    "radio",
    "range_slider",
    "refresh",
    "run_button",
    "slider",
    "switch",
    "table",
    "tabs",
    "text",
    "text_area",
]

from signalpilot._plugins.ui._impl.altair_chart import altair_chart
from signalpilot._plugins.ui._impl.array import array
from signalpilot._plugins.ui._impl.batch import batch
from signalpilot._plugins.ui._impl.data_editor import (
    data_editor,
    experimental_data_editor,
)
from signalpilot._plugins.ui._impl.data_explorer import data_explorer
from signalpilot._plugins.ui._impl.dataframes.dataframe import dataframe
from signalpilot._plugins.ui._impl.dates import (
    date,
    date_range,
    datetime,
)
from signalpilot._plugins.ui._impl.dictionary import dictionary
from signalpilot._plugins.ui._impl.file_browser import file_browser
from signalpilot._plugins.ui._impl.from_anywidget import anywidget
from signalpilot._plugins.ui._impl.from_panel import panel
from signalpilot._plugins.ui._impl.input import (
    button,
    checkbox,
    code_editor,
    dropdown,
    file,
    form,
    multiselect,
    number,
    radio,
    range_slider,
    slider,
    text,
    text_area,
)
from signalpilot._plugins.ui._impl.matrix import matrix
from signalpilot._plugins.ui._impl.microphone import microphone
from signalpilot._plugins.ui._impl.mpl import matplotlib
from signalpilot._plugins.ui._impl.plotly import plotly
from signalpilot._plugins.ui._impl.refresh import refresh
from signalpilot._plugins.ui._impl.run_button import run_button
from signalpilot._plugins.ui._impl.switch import switch
from signalpilot._plugins.ui._impl.table import table
from signalpilot._plugins.ui._impl.tabs import tabs
