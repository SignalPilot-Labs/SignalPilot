# Copyright 2026 SignalPilot. All rights reserved.
"""Markdown conversion utilities for sp notebooks.

This module provides bidirectional conversion between markdown and sp IR:
- `to_ir`: Parse markdown (.md, .qmd) files into sp notebook IR
- `from_ir`: Export sp notebook IR to markdown format
"""

from __future__ import annotations

from signalpilot._convert.markdown.from_ir import convert_from_ir_to_markdown
from signalpilot._convert.markdown.to_ir import (
    convert_from_md_to_signalpilot_ir,
    extract_frontmatter,
    formatted_code_block,
    is_sanitized_markdown,
    sanitize_markdown,
)

__all__ = [
    # Export (IR → Markdown)
    "convert_from_ir_to_markdown",
    # Import (Markdown → IR)
    "convert_from_md_to_signalpilot_ir",
    # Utilities
    "extract_frontmatter",
    "formatted_code_block",
    "is_sanitized_markdown",
    "sanitize_markdown",
]
