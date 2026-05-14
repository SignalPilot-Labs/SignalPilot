# SignalPilot Workspaces

Workspaces is a governed AI agent product built on the SignalPilot platform. It lets users run Claude Code agents against their connected data warehouses and dbt projects — with credential isolation, approval gates, and a dashboard editor powered by ECharts.

This directory contains the Workspaces product. It lives alongside `signalpilot/`, `sp-sandbox/`, and `plugin/` in the same monorepo.

**Round 1 scaffolding only.** No service is running yet. See `ARCHITECTURE.md` for the full design and the multi-round delivery plan.

## Layout

```
workspaces/
  ARCHITECTURE.md    full product design (start here)
  pricing.md         pricing framework and open questions
  agent/             sandbox runtime: vendored AutoFyn (trimmed) + CLAUDE.md
  api/               FastAPI service skeleton (routes in Round 2)
  dashboards/        chart engine + saved-dashboard models (Round 3)
  dbt_projects/      dbt link adapters: Cloud OAuth, GitHub, native upload (Round 4)
```

## Rounds

See `ARCHITECTURE.md §9` for the full delivery plan. In brief:

- **R1** — scaffolding, vendored sandbox, CLAUDE.md, pricing, architecture docs (this)
- **R2** — workspaces-api routes + Postgres schema
- **R3** — gateway dbt-proxy + credential isolation runtime
- **R4** — dbt link adapters
- **R5** — web UI in `signalpilot/web/app/workspaces/`
- **R6** — approval flow + end-to-end streaming
- **R7** — Docker Compose service wiring + local-mode demo
- **R8** — hardening, governance integration tests, docs
