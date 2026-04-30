"""MCP schema tools package.

Split from ``mcp/tools/schema.py`` (949 LOC) in round 9.

Invariant: MCP ``@audited_tool`` decoration order — ``mcp.list_tools()`` must
return tools in original registration order; submodule imports must not be
reordered. Decoration runs at import time and registers onto the FastMCP
singleton.

``# isort: skip_file`` is mandatory: reordering imports changes tool
registration order and alters ``mcp.list_tools()`` iteration.

Do not add ``__getattr__`` proxy or ``_common.py`` re-export helpers — see r9 lessons.
"""
# isort: skip_file

from __future__ import annotations

# Side-effect imports — order MUST match original decoration order
# (lines 18, 111, 195, 290, 337, 380, 456, 557, 611, 654, 703, 816, 884).
from gateway.mcp.tools.schema import catalog as _catalog  # noqa: F401  # describe_table(18), list_tables(111)
from gateway.mcp.tools.schema import dates as _dates  # noqa: F401  # get_date_boundaries(195)
from gateway.mcp.tools.schema import relationships as _rel  # noqa: F401  # find_join_path(290), get_relationships(337)
from gateway.mcp.tools.schema import exploration_table as _expl_tbl  # noqa: F401  # explore_table(380)
from gateway.mcp.tools.schema import summary as _summary  # noqa: F401  # schema_overview(456)
from gateway.mcp.tools.schema import ddl as _ddl  # noqa: F401  # schema_diff(557), schema_ddl(611), schema_link(654)
from gateway.mcp.tools.schema import exploration_columns as _expl_col  # noqa: F401  # explore_columns(703)
from gateway.mcp.tools.schema import stats as _stats  # noqa: F401  # schema_statistics(816)
from gateway.mcp.tools.schema import explore_value as _expl_val  # noqa: F401  # explore_column(884)

# Re-exports for the sole importer (gateway.mcp package re-exports) and any defensive patches.
from gateway.mcp.tools.schema.catalog import describe_table, list_tables
from gateway.mcp.tools.schema.dates import get_date_boundaries
from gateway.mcp.tools.schema.relationships import find_join_path, get_relationships
from gateway.mcp.tools.schema.exploration_table import explore_table
from gateway.mcp.tools.schema.summary import schema_overview
from gateway.mcp.tools.schema.ddl import schema_diff, schema_ddl, schema_link
from gateway.mcp.tools.schema.exploration_columns import explore_columns
from gateway.mcp.tools.schema.stats import schema_statistics
from gateway.mcp.tools.schema.explore_value import explore_column

__all__ = [
    "describe_table",
    "list_tables",
    "get_date_boundaries",
    "find_join_path",
    "get_relationships",
    "explore_table",
    "schema_overview",
    "schema_diff",
    "schema_ddl",
    "schema_link",
    "explore_columns",
    "schema_statistics",
    "explore_column",
]
