"""
Topological sort for dbt model build order.

Given the full project model dict and the set of known model names, compute:
  - order: a topological ordering of actionable models (missing + stub) such
    that every model appears after all of its resolvable dependencies
  - unresolved: {model: [refs_that_dont_exist]} so the agent can flag
    typos or missing imports
  - cycles: list of cycle member lists for debugging

Uses Kahn's algorithm on the subgraph induced by actionable models plus
their dependencies. Complete/orphan models are treated as "already built" —
they satisfy dependencies but aren't included in the output order.

Why not rely on dbt's own DAG from manifest.json? Because the manifest drops
missing models entirely (empirically verified), so the DAG would be wrong.
This is a smaller, domain-specific topological sort over the yml-discovered
models and the sql-extracted refs, which is always available.
"""

from __future__ import annotations

from collections import defaultdict, deque

from .types import ModelInfo


def compute_work_order(
    models: dict[str, ModelInfo],
    known_names: set[str],
) -> dict:
    """Compute topological build order for actionable (missing+stub) models.

    Returns a dict with keys:
      - order: list[str] of model names in build order
      - unresolved: dict[str, list[str]] — per-model refs that don't resolve
      - cycles: list[list[str]] — cycle member lists, empty if acyclic
    """
    actionable = {name: m for name, m in models.items() if m.status.is_actionable()}
    if not actionable:
        return {"order": [], "unresolved": {}, "cycles": []}

    # Build the dependency graph over the full model set, so an actionable
    # model that depends on a non-actionable (complete) one still orders correctly.
    edges_out: dict[str, set[str]] = defaultdict(set)  # name -> deps it needs
    edges_in: dict[str, set[str]] = defaultdict(set)  # name -> dependents waiting on it
    unresolved: dict[str, list[str]] = {}

    for name, m in actionable.items():
        for ref in m.all_refs:
            if ref in known_names:
                edges_out[name].add(ref)
                edges_in[ref].add(name)
            else:
                unresolved.setdefault(name, []).append(ref)

    # Kahn's algorithm — start from models whose deps are all resolved
    # (either non-actionable = already built, or not in our subgraph at all).
    # For the topological sort, we only sort actionable models but respect
    # their edges to non-actionable ones as "already satisfied".

    in_degree: dict[str, int] = {}
    for name in actionable:
        count = 0
        for dep in edges_out[name]:
            if dep in actionable:
                count += 1
        in_degree[name] = count

    queue: deque[str] = deque(sorted(n for n, d in in_degree.items() if d == 0))
    order: list[str] = []
    while queue:
        node = queue.popleft()
        order.append(node)
        # Decrement in-degree of every actionable model that depends on this one.
        for dependent in sorted(edges_in[node]):
            if dependent not in actionable:
                continue
            in_degree[dependent] -= 1
            if in_degree[dependent] == 0:
                queue.append(dependent)

    # Any actionable model not in order is part of a cycle (or depends on one).
    remaining = {n for n in actionable if n not in order}
    cycles: list[list[str]] = []
    if remaining:
        cycles = _extract_cycles(remaining, edges_out)
        # Fall back to name-sorted order for cycle members so we still emit them.
        order.extend(sorted(remaining))

    return {"order": order, "unresolved": unresolved, "cycles": cycles}


def _extract_cycles(
    remaining: set[str],
    edges_out: dict[str, set[str]],
) -> list[list[str]]:
    """Find the cycles among the models that couldn't be topologically sorted.

    Uses a DFS with a recursion stack to detect back edges. Returns each cycle
    as a list of node names in cycle order. Does NOT attempt to find every
    cycle — just enough to explain why the sort stalled.
    """
    cycles: list[list[str]] = []
    visited: set[str] = set()
    stack: list[str] = []
    on_stack: set[str] = set()

    def dfs(node: str) -> None:
        if node in on_stack:
            # Found a cycle: slice from node's first appearance to the top of the stack.
            start = stack.index(node)
            cycle = stack[start:] + [node]
            if cycle not in cycles:
                cycles.append(cycle)
            return
        if node in visited:
            return
        visited.add(node)
        stack.append(node)
        on_stack.add(node)
        for dep in sorted(edges_out.get(node, [])):
            if dep in remaining:
                dfs(dep)
        stack.pop()
        on_stack.discard(node)

    for start_node in sorted(remaining):
        if start_node not in visited:
            dfs(start_node)

    return cycles
