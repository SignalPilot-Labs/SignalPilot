"""Provide the entry points for the dbt benchmark runners.

Each submodule provides a `main()` entry point. Use the full module path to run a submodule.

For example, use `python -m benchmark.runners.kb_generator <instance_id>`.

Submodules:
    direct: Runs a dbt task through the Claude Agent SDK without Docker.
    sql_runner: Runs the Spider2 SQL suites for Snowflake and SQLite.
    kb_generator: Generates knowledge-base entries for a task.
"""
