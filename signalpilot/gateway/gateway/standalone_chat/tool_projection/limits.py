"""Size caps for tool-result projections persisted on ``tool_completed`` events.

Every cap here bounds what one event can carry to the browser. Raising any of
them grows ``get_conversation_detail`` linearly in the number of tool calls.
"""

from __future__ import annotations

# Raw text copy attached to every projection (``result_text``).
RESULT_TEXT_MAX = 8192
# Shrunk ``result_text`` used when the payload is still over PAYLOAD_MAX.
RESULT_TEXT_SHRUNK = 2048

# kind="table"
TABLE_ROWS_MAX = 50
TABLE_ROWS_SHRUNK = 20
TABLE_COLS_MAX = 30
CELL_MAX = 200

# kind="table_list"
TABLE_LIST_MAX = 200
TABLE_LIST_SHRUNK = 50
TABLE_LIST_COLS_MAX = 60

# kind="schema" / kind="column_profile"
SCHEMA_COLS_MAX = 300
SCHEMA_COLS_SHRUNK = 100
SAMPLE_VALUES_MAX = 10
TOP_VALUES_MAX = 25

# kind="knowledge"
KNOWLEDGE_DOCS_MAX = 50
KNOWLEDGE_SNIPPET_MAX = 400

# kind="terminal" / kind="dbt_run" / kind="json"
TERMINAL_TEXT_MAX = 8192
DBT_LOG_MAX = 8192
DBT_FAILURES_MAX = 10
JSON_MAX = 8192
JSON_DEPTH_MAX = 5
JSON_KEYS_MAX = 50
JSON_ITEMS_MAX = 20
JSON_STR_MAX = 500

# Whole-payload guarantees.
SUMMARY_MAX = 300
ERROR_TEXT_MAX = 4000
PAYLOAD_MAX = 65536
# Cached tool input echoed into the projection (worker side).
INPUT_ECHO_MAX = 2048
