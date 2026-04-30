"""Static-analysis + deterministic fix helpers for dbt project directories.

Submodules:
    scanner      — extract model names, columns, deps, descriptions from yml/sql
    templates    — create starter SQL files + ephemeral stubs for missing refs
"""
