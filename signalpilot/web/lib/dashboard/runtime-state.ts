import type {
  ChartDefinition,
  DashboardDefinition,
  DashboardDrillStep,
  DashboardFilterRule,
  DashboardQueryResult,
  DashboardRuntimeFilter,
} from "~/lib/dashboard/contracts";

export type DashboardRuntimeState = {
  filters: DashboardRuntimeFilter[];
  drills: Record<string, DashboardDrillStep[]>;
};

export function chartForAvailableResult(
  chart: ChartDefinition,
  result: DashboardQueryResult | undefined,
): ChartDefinition {
  if (chart.query.kind !== "semantic" || !result) return chart;
  const baseDimensions = chart.query.dimensions.slice(-1);
  const configured =
    chart.signalPilot.drillDimensions ?? chart.signalPilot.tableGroups ?? [];
  const hierarchy = [
    ...baseDimensions,
    ...configured.filter((field) => !baseDimensions.includes(field)),
  ];
  const available = new Set(result.columns.map((column) => column.name));
  const displayedDimension = hierarchy.findLast((field) =>
    available.has(field),
  );
  if (!displayedDimension) return chart;
  if (chart.visualization.type === "cartesian") {
    return {
      ...chart,
      visualization: {
        ...chart.visualization,
        config: {
          ...chart.visualization.config,
          layout: {
            ...chart.visualization.config.layout,
            xField: displayedDimension,
          },
        },
      },
    };
  }
  if (chart.visualization.type === "table") {
    const base = new Set(chart.query.dimensions);
    return {
      ...chart,
      visualization: {
        ...chart.visualization,
        config: {
          ...chart.visualization.config,
          columns: chart.visualization.config.columns.map((column) =>
            base.has(column) ? displayedDimension : column,
          ),
        },
      },
    };
  }
  return chart;
}

const scalar = (value: unknown): value is string | number | boolean | null =>
  value === null || ["string", "number", "boolean"].includes(typeof value);

const operators = new Set([
  "equals",
  "isNull",
  "notNull",
  "inBetween",
  "inThePast",
  "inTheCurrent",
  "inPeriodToDate",
]);

export function initialDashboardRuntimeState(
  definition: DashboardDefinition,
): DashboardRuntimeState {
  return {
    filters: definition.filters.dimensions
      .filter(
        (rule) =>
          Boolean(rule.values?.length) ||
          rule.operator === "isNull" ||
          rule.operator === "notNull",
      )
      .map(({ id, operator, values, settings }) => ({
        id,
        operator,
        values,
        settings,
      })),
    drills: {},
  };
}

export function parseDashboardRuntimeState(
  definition: DashboardDefinition,
  search: string,
): DashboardRuntimeState {
  const fallback = initialDashboardRuntimeState(definition);
  const params = new URLSearchParams(search);
  const knownFilters = new Map(
    definition.filters.dimensions.map((rule) => [rule.id, rule]),
  );
  try {
    const rawFilters = params.get("filters");
    if (rawFilters) {
      const parsed = JSON.parse(rawFilters) as {
        dimensions?: Array<Partial<DashboardFilterRule>>;
      };
      if (!Array.isArray(parsed.dimensions)) throw new Error("Invalid filters");
      fallback.filters = parsed.dimensions.map((rule) => {
        if (
          typeof rule.id !== "string" ||
          !knownFilters.has(rule.id) ||
          typeof rule.operator !== "string" ||
          !operators.has(rule.operator) ||
          (rule.values && !rule.values.every(scalar))
        ) {
          throw new Error("Invalid filter override");
        }
        return {
          id: rule.id,
          operator: rule.operator as DashboardRuntimeFilter["operator"],
          values: rule.values,
          settings: rule.settings,
        };
      });
    }
    const rawDrills = params.get("drillPath");
    if (rawDrills) {
      const parsed = JSON.parse(rawDrills) as Array<{
        chartId?: unknown;
        fieldId?: unknown;
        value?: unknown;
      }>;
      if (!Array.isArray(parsed)) throw new Error("Invalid drill path");
      for (const step of parsed) {
        if (
          typeof step.chartId !== "string" ||
          typeof step.fieldId !== "string" ||
          !scalar(step.value) ||
          !definition.charts.some((chart) => chart.id === step.chartId)
        ) {
          throw new Error("Invalid drill step");
        }
        fallback.drills[step.chartId] = [
          ...(fallback.drills[step.chartId] ?? []),
          { fieldId: step.fieldId, value: step.value },
        ];
      }
    }
  } catch {
    return initialDashboardRuntimeState(definition);
  }
  return fallback;
}

export function runtimeStateSearchParams(
  definition: DashboardDefinition,
  state: DashboardRuntimeState,
): Pick<URLSearchParams, "toString"> {
  const params = new URLSearchParams();
  const byId = new Map(
    definition.filters.dimensions.map((rule) => [rule.id, rule]),
  );
  params.set(
    "filters",
    JSON.stringify({
      dimensions: state.filters.map((filter) => ({
        ...byId.get(filter.id),
        ...filter,
      })),
      metrics: [],
      tableCalculations: [],
    }),
  );
  const drills = Object.entries(state.drills).flatMap(([chartId, steps]) =>
    steps.map((step) => ({ chartId, ...step })),
  );
  if (drills.length) params.set("drillPath", JSON.stringify(drills));
  return params;
}

export function toggleCrossFilter(
  filters: DashboardRuntimeFilter[],
  rule: DashboardFilterRule,
  value: string | number | boolean | null,
  multiselect: boolean,
): DashboardRuntimeFilter[] {
  const current = filters.find((filter) => filter.id === rule.id);
  const currentValues = current?.values ?? [];
  let values: Array<string | number | boolean | null>;
  if (multiselect) {
    values = currentValues.some((item) => Object.is(item, value))
      ? currentValues.filter((item) => !Object.is(item, value))
      : [...currentValues, value];
  } else {
    values =
      currentValues.length === 1 && Object.is(currentValues[0], value)
        ? []
        : [value];
  }
  return [
    ...filters.filter((filter) => filter.id !== rule.id),
    ...(values.length
      ? [{ id: rule.id, operator: "equals" as const, values }]
      : []),
  ];
}

export function markRemainsSelected(
  filters: DashboardRuntimeFilter[],
  filterId: string,
  mark: Record<string, unknown>,
  fieldId: string,
): boolean {
  const values = filters.find((filter) => filter.id === filterId)?.values;
  return Boolean(values?.length === 1 && Object.is(values[0], mark[fieldId]));
}
