"""Shared infrastructure for the dbt benchmark runners.

Submodules:
    paths     — resolved filesystem locations for Spider2 data + workdirs
    logging   — tiny logging helpers (log, log_separator)
    tasks     — load_task / load_eval_config helpers
    workdir   — prepare_workdir, write_claude_md, _force_rmtree
    mcp       — MCP config loader + SignalPilot connection registration
"""
