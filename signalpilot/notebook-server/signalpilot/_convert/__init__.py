"""
sp._convert - Format conversion utilities for sp notebooks.

Provides bidirectional conversion between sp's internal representation
and various notebook/script formats.
"""

from __future__ import annotations

# Only import the main converters at module level to avoid circular imports.
# Other conversion functions should be imported directly from their submodules:
#   from signalpilot._convert.markdown import convert_from_ir_to_markdown
#   from signalpilot._convert.ipynb import convert_from_ipynb_to_notebook_ir
#   etc.
from signalpilot._convert.converters import (
    SpConvert,
    SpConverterIntermediate,
)

__all__ = [
    "SpConvert",
    "SpConverterIntermediate",
]
