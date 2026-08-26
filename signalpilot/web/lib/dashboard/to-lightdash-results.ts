import type {
  ChartDefinition,
  DashboardQueryResult,
  DashboardResultColumn,
  LightdashCartesianInput,
  LightdashField,
  LightdashResultValue,
} from "~/lib/dashboard/contracts";
import {
  fieldLabel,
  formatDashboardCell,
} from "~/lib/dashboard/semantic-formatter";

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
          label: column.label ?? fieldLabel(field),
          type: column.logicalType,
          role: field === layout.xField ? "dimension" : "metric",
          format: column.format,
          currencyCode: column.currencyCode,
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
          formatted: formatDashboardCell(row[field], column, result),
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
    locale: result.locale,
    timezone: result.timezone,
  };
}
