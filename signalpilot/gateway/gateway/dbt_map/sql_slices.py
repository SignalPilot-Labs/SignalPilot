"""Per-node SQL for the lineage UI: artifact extraction and response shaping.

The SQL map is `{unique_id: {"raw": str|None, "compiled": str|None,
"language": str}}` for non-test nodes. The compile pipeline writes it as
sql.json.gz next to the distilled graph; older maps derive the same dict
from the stored manifest on first request.
"""

from __future__ import annotations

from .slices import TEST_TYPES

SQL_CAP_BYTES = 512 * 1024
SQL_RESOURCE_TYPES = frozenset({"model", "seed", "snapshot"})


def extract_sql_map(nodes: dict) -> dict[str, dict]:
    """Only the code fields, only for non-test nodes."""
    out: dict[str, dict] = {}
    for uid, node in nodes.items():
        if not isinstance(node, dict) or node.get("resource_type") in TEST_TYPES:
            continue
        out[uid] = {
            "raw": node.get("raw_code"),
            "compiled": node.get("compiled_code"),
            "language": node.get("language") or "sql",
        }
    return out


def _cap(text: str | None) -> tuple[str | None, bool]:
    if text is None:
        return None, False
    encoded = text.encode("utf-8")
    if len(encoded) <= SQL_CAP_BYTES:
        return text, False
    return encoded[:SQL_CAP_BYTES].decode("utf-8", errors="ignore"), True


def sql_payload(uid: str, node: dict, entry: dict | None, source: str) -> dict:
    """Response body for /dbt-map/model/{ref}/sql."""
    entry = entry or {}
    raw, raw_cut = _cap(entry.get("raw"))
    compiled, compiled_cut = _cap(entry.get("compiled"))
    return {
        "unique_id": uid,
        "name": node.get("name"),
        "path": node.get("path"),
        "original_file_path": node.get("original_file_path"),
        "language": entry.get("language") or "sql",
        "raw_sql": raw,
        "compiled_sql": compiled,
        "source": source,
        "truncated": raw_cut or compiled_cut,
    }
