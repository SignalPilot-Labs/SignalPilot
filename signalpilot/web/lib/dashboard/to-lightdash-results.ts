import type {
  ChartDefinition,
  DashboardQueryResult,
  DashboardResultColumn,
  LightdashCartesianInput,
  LightdashField,
  LightdashResultValue,
} from "~/lib/dashboard/contracts";

function formatValue(value: unknown, column: DashboardResultColumn): string {
  if (value === null || value === undefined) return "—";

  if (column.logicalType === "number" && typeof value === "number") {
    return new Intl.NumberFormat("en-US", {
      maximumFractionDigits: 2,
    }).format(value);
  }

  if (
    (column.logicalType === "date" || column.logicalType === "timestamp") &&
    (typeof value === "string" || value instanceof Date)
  ) {
    const date = value instanceof Date ? value : new Date(value);
    if (!Number.isNaN(date.valueOf())) {
      return new Intl.DateTimeFormat("en-US", {
        dateStyle: "medium",
      }).format(date);
    }
  }

  if (column.logicalType === "boolean" && typeof value === "boolean") {
    return value ? "Yes" : "No";
  }

  return String(value);
}

export function toLightdashCartesianInput(
  result: DashboardQueryResult,
  chart: ChartDefinition,
): LightdashCartesianInput {
  if (chart.visualization.type !== "cartesian") {
    throw new Error(`Chart '${chart.id}' is not cartesian`);
  }
  const { layout, seriesType } = chart.visualization.config;
  const selectedFields = [layout.xField, ...layout.yField];
  const columns = new Map(
    result.columns.map((column) => [column.name, column]),
  );

  for (const field of selectedFields) {
    if (!columns.has(field)) {
      throw new Error(`Dashboard result is missing required field '${field}'`);
    }
  }

  const fields = Object.fromEntries(
    selectedFields.map((field): [string, LightdashField] => {
      const column = columns.get(field)!;
      return [
        field,
        {
          fieldId: field,
          label: column.label ?? field,
          type: column.logicalType,
          role: field === layout.xField ? "dimension" : "metric",
        },
      ];
    }),
  );

  const rows = result.rows.map((row) =>
    Object.fromEntries(
      selectedFields.map((field) => {
        const column = columns.get(field)!;
        const value: LightdashResultValue = {
          raw: row[field],
          formatted: formatValue(row[field], column),
        };
        return [field, { value }];
      }),
    ),
  );

  return {
    chartType: "cartesian",
    seriesType,
    xField: layout.xField,
    yFields: layout.yField,
    rows,
    fields,
  };
}
