import type { DashboardFilter } from "~/lib/dashboard/contracts";

/**
 * Adapted from Lightdash DashboardChartTile's cross-filter construction and
 * DrillDownModal's combineFilters behavior. See ../UPSTREAM.md.
 */
export function createTemporaryDashboardFilter(
  field: string,
  value: unknown,
): DashboardFilter {
  return { field, operator: "equals", value, temporary: true };
}

export function combineDrillFilters(
  dashboardFilters: DashboardFilter[],
  clickedValues: Record<string, unknown>,
  dimensions: string[],
): DashboardFilter[] {
  const clickedFilters = dimensions
    .filter((field) => field in clickedValues)
    .map((field) =>
      createTemporaryDashboardFilter(field, clickedValues[field]),
    );

  return [
    ...dashboardFilters.filter(
      ({ field }) => !clickedFilters.some((filter) => filter.field === field),
    ),
    ...clickedFilters,
  ];
}
