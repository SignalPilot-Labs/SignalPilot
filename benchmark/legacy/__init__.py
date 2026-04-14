"""Legacy Spider2-SQLite benchmark cluster.

These modules predate the dbt benchmark and are kept for reference/reuse.
They form a self-contained import cluster:

    run → config, eval, setup_spider2, skills, agent_runner
    agent_runner → config, eval, skills
    improve → config
    setup_spider2 → config
    skills → config

None of them are imported by the active dbt benchmark runners.
"""
