# Lightdash extraction provenance

Parts of this package are adapted from the MIT-licensed Lightdash frontend.

- Upstream repository: `https://github.com/lightdash/lightdash`
- Contract baseline commit: `b91bd2273f38fdc58702c71f538b6b5d5ae462c5`
- Recorded from the pinned local fork on: `2026-08-24`
- License: `LICENSE.lightdash`

## What was adapted

- `charts/options.ts` and `charts/axes.ts`: the ECharts option structure for
  bar and line charts (axis styling, grid margins, legend placement, tooltip
  formatting, bar radius and widths) is adapted from
  `packages/frontend/src/components/SimpleChart/index.tsx`, by way of the
  Lightdash extraction formerly vendored in this repo (removed 2026-09-08).
- `charts/echarts-tile.tsx`: the `echarts-for-react` wrapper follows
  `packages/frontend/src/components/EChartsReactWrapper.tsx`.

Everything else in this package (schema, dataset parsing, row preparation,
layout, formatting, print path) is SignalPilot code. No browser request is made
to a Lightdash endpoint.
