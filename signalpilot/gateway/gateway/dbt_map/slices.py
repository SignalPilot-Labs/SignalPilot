"""Derived views of a distilled dbt graph.

All functions are pure and operate on the graph dict produced by
runner.distill_graph. They back the `graph=skeleton`, `/columns` and
`/model/{ref}` payload variants; results are memoized per graph_key by
graph_cache, so nothing here needs to be fast on repeat calls.
"""

from __future__ import annotations

from collections import deque

TEST_TYPES = frozenset({"test", "unit_test"})
MAX_TESTS_PER_NODE = 40
MAX_COLUMN_IDS = 50


def is_test_node(node: dict | None) -> bool:
    return bool(node) and node.get("resource_type") in TEST_TYPES


def _keep(uid: str, nodes: dict) -> bool:
    # Ids missing from nodes (sources, exposures) are kept; only tests drop.
    return not is_test_node(nodes.get(uid))


def _trim_test(node: dict) -> dict:
    out: dict = {"name": node.get("name")}
    meta = node.get("test_metadata")
    if isinstance(meta, dict):
        trimmed: dict = {"name": meta.get("name")}
        column = (meta.get("kwargs") or {}).get("column_name")
        if column is not None:
            trimmed["kwargs"] = {"column_name": column}
        out["test_metadata"] = trimmed
    return out


def skeleton_node(uid: str, node: dict, graph: dict) -> dict:
    """A node without columns, plus column_count and its attached test chips."""
    nodes = graph.get("nodes") or {}
    slim = {k: v for k, v in node.items() if k != "columns"}
    slim["column_count"] = len(node.get("columns") or {})
    tests: list[dict] = []
    for child_id in (graph.get("child_map") or {}).get(uid, []):
        child = nodes.get(child_id)
        if child is not None and is_test_node(child):
            tests.append(_trim_test(child))
            if len(tests) >= MAX_TESTS_PER_NODE:
                break
    slim["tests"] = tests
    return slim


def _filter_map(mapping: dict, nodes: dict) -> dict:
    return {
        uid: [c for c in children if _keep(c, nodes)]
        for uid, children in mapping.items()
        if _keep(uid, nodes)
    }


def build_skeleton(graph: dict) -> dict:
    """Full graph minus tests and columns; test chips folded onto their parents."""
    nodes = graph.get("nodes") or {}
    return {
        "metadata": {**(graph.get("metadata") or {}), "variant": "skeleton"},
        "nodes": {uid: skeleton_node(uid, n, graph) for uid, n in nodes.items() if not is_test_node(n)},
        "sources": graph.get("sources") or {},
        "parent_map": _filter_map(graph.get("parent_map") or {}, nodes),
        "child_map": _filter_map(graph.get("child_map") or {}, nodes),
    }


def columns_list(node: dict | None) -> list[dict]:
    out: list[dict] = []
    for name, col in ((node or {}).get("columns") or {}).items():
        col = col or {}
        item = {"name": col.get("name") or name, "description": col.get("description") or ""}
        if col.get("data_type") is not None:
            item["data_type"] = col["data_type"]
        out.append(item)
    return out


def columns_for(graph: dict, ids: list[str]) -> dict[str, list[dict]]:
    """Columns for the requested ids; unknown ids are omitted."""
    nodes = graph.get("nodes") or {}
    sources = graph.get("sources") or {}
    out: dict[str, list[dict]] = {}
    for uid in ids:
        node = nodes.get(uid) or sources.get(uid)
        if node is not None:
            out[uid] = columns_list(node)
    return out


def resolve_ref(graph: dict, ref: str) -> tuple[str | None, list[str]]:
    """Exact unique_id first, then a unique case-insensitive non-test name.

    Returns (unique_id, candidates). candidates is non-empty only when the
    name is ambiguous; both empty means unknown.
    """
    nodes = graph.get("nodes") or {}
    if ref in nodes or ref in (graph.get("sources") or {}):
        return ref, []
    wanted = ref.lower()
    candidates = sorted(
        uid
        for uid, node in nodes.items()
        if not is_test_node(node) and (node.get("name") or "").lower() == wanted
    )
    if len(candidates) == 1:
        return candidates[0], []
    return None, candidates


def _walk(start: str, adjacency: dict, nodes: dict, hops: int | None) -> set[str]:
    seen: set[str] = set()
    queue: deque[tuple[str, int]] = deque([(start, 0)])
    while queue:
        uid, depth = queue.popleft()
        if hops is not None and depth >= hops:
            continue
        for nxt in adjacency.get(uid, []):
            if nxt in seen or nxt == start or not _keep(nxt, nodes):
                continue
            seen.add(nxt)
            queue.append((nxt, depth + 1))
    return seen


def _source_stub(uid: str) -> dict:
    parts = uid.split(".")
    return {
        "name": parts[-1],
        "resource_type": "source",
        "column_count": 0,
        "tests": [],
    }


def build_cone(graph: dict, uid: str, hops: int | None) -> dict:
    """Focused model with its ancestor + descendant cone as skeleton nodes."""
    nodes = graph.get("nodes") or {}
    sources = graph.get("sources") or {}
    parent_map = graph.get("parent_map") or {}
    child_map = graph.get("child_map") or {}

    upstream = _walk(uid, parent_map, nodes, hops)
    downstream = _walk(uid, child_map, nodes, hops)
    ids = {uid} | upstream | downstream

    cone_nodes: dict[str, dict] = {}
    for nid in sorted(ids):
        node = nodes.get(nid)
        if node is not None:
            cone_nodes[nid] = skeleton_node(nid, node, graph)
        elif nid in sources:
            cone_nodes[nid] = skeleton_node(nid, sources[nid], graph)
        elif nid.startswith("source."):
            cone_nodes[nid] = _source_stub(nid)

    focus = nodes.get(uid) or sources.get(uid) or {}
    model = {"unique_id": uid, **skeleton_node(uid, focus, graph), "columns": columns_list(focus)}
    return {
        "model": model,
        "graph": {
            "metadata": {**(graph.get("metadata") or {}), "variant": "cone"},
            "nodes": cone_nodes,
            "sources": {nid: sources[nid] for nid in sorted(ids) if nid in sources},
            "parent_map": {k: [c for c in parent_map[k] if c in ids] for k in sorted(ids) if k in parent_map},
            "child_map": {k: [c for c in child_map[k] if c in ids] for k in sorted(ids) if k in child_map},
        },
        "cone": {"upstream": len(upstream), "downstream": len(downstream)},
    }
