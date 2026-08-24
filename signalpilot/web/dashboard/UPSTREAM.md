# Lightdash extraction provenance

This directory contains a focused extraction from the MIT-licensed Lightdash frontend.

- Upstream repository: `https://github.com/lightdash/lightdash`
- Contract baseline commit: `b91bd2273f38fdc58702c71f538b6b5d5ae462c5`
- Recorded from the pinned local fork on: `2026-08-24`
- License: `LICENSE.lightdash`

## Prototype extraction

- `lightdash/EChartsReactWrapper.tsx` is copied from
  `packages/frontend/src/components/EChartsReactWrapper.tsx`.
- `lightdash/LightdashCartesianChart.tsx` is a deliberately decoupled extraction
  of the bar-chart rendering behavior from
  `packages/frontend/src/components/SimpleChart/index.tsx`. It keeps ECharts,
  Lightdash-style result values, screenshot readiness, click events, loading,
  and empty states while removing Lightdash API, router, auth, permissions,
  explorer, and dashboard-provider dependencies.
- `lightdash/filter-interactions.ts` adapts cross-filter construction from
  `DashboardChartTile.tsx` and drill filter combination from
  `MetricQueryData/DrillDownModal.tsx`.

SignalPilot owns the result adapter, dashboard shell, grid, querying, persistence,
authorization, and AI context. No browser request is made to a Lightdash endpoint.

## Deliberately excluded

- `pages/MinimalDashboard.tsx`
- `components/DashboardTiles/DashboardChartTile.tsx`
- `providers/Dashboard/DashboardProvider.tsx`
- `features/dashboardTabs/index.tsx`
- `features/dashboardFilters/`
- `hooks/useQueryResults.ts`
- `packages/frontend/src/ee/`

The prototype adds further Lightdash chart and table slices only after the
SignalPilot result adapter and MSSQL data-source seam are proven.

## Contract extraction

- `lightdash-contract/types.ts` adapts the minimum supported subset of
  dashboard, tile, filter, metric query, sort, chart-config, and version types.
- `lightdash-contract/schema.ts` is the strict runtime validator for the
  browser/server TypeScript boundary.
- `CONTRACT_MAPPING.md` records every mapped field and SignalPilot extension.
- Unsupported Lightdash variants fail explicitly; they are not dropped.
