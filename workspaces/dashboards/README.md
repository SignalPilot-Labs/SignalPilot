# Workspaces Dashboards

Chart engine and saved-dashboard models for Workspaces. Round 3 fills the implementation.

## Stack

- **Charts:** Apache ECharts via `echarts-for-react` (see `ARCHITECTURE.md §5` for rationale)
- **Storage:** Postgres schema `workspaces` (see `ARCHITECTURE.md §7` for data model)
- **Cache:** Arrow IPC payloads in `chart_cache` table (`bytea`)

## Package Layout

```
workspaces/dashboards/
  workspaces_dashboards/
    __init__.py
    models.py          placeholder — data model documented in ARCHITECTURE.md §7
    charts/
      __init__.py      ECharts option builders (Round 3)
```

No `pyproject.toml` in Round 1. Added in Round 3 when installable code is present.
