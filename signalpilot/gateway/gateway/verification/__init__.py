"""Structured verification services shared by MCP and product surfaces."""

from .model_schema import ColumnComparison, compare_columns

__all__ = ["ColumnComparison", "compare_columns"]
