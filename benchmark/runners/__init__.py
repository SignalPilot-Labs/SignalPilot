"""Top-level orchestration for the dbt benchmark runners.

Each submodule exposes a `main()` entrypoint; the original top-level
benchmark/run_*.py files are thin shims that re-export that main().

Submodules:
    direct  — runs a task via the Claude Agent SDK directly (no Docker)
"""
