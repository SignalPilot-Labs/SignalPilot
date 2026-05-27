# Copyright 2026 SignalPilot. All rights reserved.
"""Jupyter notebook (.ipynb) conversion utilities for sp notebooks.

This module provides bidirectional conversion between ipynb and sp IR:
- `to_ir`: Parse Jupyter notebooks into sp notebook IR
- `from_ir`: Export sp notebook IR to Jupyter notebook format
"""

from __future__ import annotations

from signalpilot._convert.ipynb.from_ir import convert_from_ir_to_ipynb
from signalpilot._convert.ipynb.to_ir import (
    CodeCell,
    ExclamationMarkResult,
    convert_from_ipynb_to_notebook_ir,
)

__all__ = [  # noqa: RUF022
    # Export (IR → ipynb)
    "convert_from_ir_to_ipynb",
    # Import (ipynb → IR)
    "convert_from_ipynb_to_notebook_ir",
    # Types
    "CodeCell",
    "ExclamationMarkResult",
]
