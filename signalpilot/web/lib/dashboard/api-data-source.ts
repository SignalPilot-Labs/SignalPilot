import { request } from "~/lib/api";
import type {
  ChartDefinition,
  DashboardDataSource,
  DashboardQueryOptions,
  DashboardQueryResult,
  DashboardTileDefinition,
} from "~/lib/dashboard/contracts";

export type DashboardQueryReceipt = {
  dashboard_result_id: string;
  result_id: string;
  execution_id: string;
  columns: Array<{
    name: string;
    logical_type: string;
    nullable: boolean;
    label?: string;
    format?: string;
    currency_code?: string;
  }>;
  rows: Record<string, unknown>[];
  completeness: "complete" | "truncated" | "unknown";
  result_time: string;
  freshness_at: string | null;
  sql_hash: string;
  parameter_hash: string;
  tables: string[];
  semantic_definition: Record<string, unknown>;
  compiled_sql: string | null;
  cache_state: "fresh" | "stale" | "miss" | "refreshed";
};

type SemanticColumnMetadata = {
  label?: string;
  format?: DashboardQueryResult["columns"][number]["format"];
  currencyCode?: string;
};

export function semanticColumnMetadata(
  receipt: Pick<DashboardQueryReceipt, "semantic_definition">,
  columnName: string,
): SemanticColumnMetadata {
  const metrics = receipt.semantic_definition.metrics;
  if (!Array.isArray(metrics)) return {};
  const metric = metrics.find(
    (candidate): candidate is Record<string, unknown> =>
      typeof candidate === "object" &&
      candidate !== null &&
      candidate.field_id === columnName,
  );
  if (!metric) return {};
  const format =
    typeof metric.format === "string"
      ? (metric.format as SemanticColumnMetadata["format"])
      : undefined;
  return {
    label: typeof metric.label === "string" ? metric.label : undefined,
    format,
    currencyCode: format?.startsWith("currency:")
      ? format.slice("currency:".length)
      : undefined,
  };
}

export class DashboardApiDataSource implements DashboardDataSource {
  constructor(
    private readonly dashboardId: string,
    private readonly versionId: string,
    private readonly onReceipt?: (
      chart: ChartDefinition,
      receipt: DashboardQueryReceipt,
    ) => void,
    private readonly authoringSessionId?: string,
    private readonly timezone = "UTC",
    private readonly locale = "en-US",
  ) {}

  async loadTile(
    tile: DashboardTileDefinition,
    chart: ChartDefinition,
    options: DashboardQueryOptions,
    signal: AbortSignal,
  ): Promise<DashboardQueryResult> {
    const queryPath =
      this.dashboardId.startsWith("draft:") && this.authoringSessionId
        ? `/api/dashboard-authoring/sessions/${this.authoringSessionId}/charts/${chart.id}/query`
        : `/api/dashboards/${this.dashboardId}/charts/${chart.id}/query`;
    const receipt = await request<DashboardQueryReceipt>(queryPath, {
      method: "POST",
      body: JSON.stringify({
        version_id: this.versionId,
        authoring_session_id: this.authoringSessionId,
        tile_uuid: tile.uuid,
        refresh: options.invalidateCache ?? false,
        dashboard_filters: options.dashboardFilters ?? [],
        drill_path: (options.dashboardDrillPath ?? []).map((step) => ({
          field_id: step.fieldId,
          value: step.value,
        })),
      }),
      signal,
    });
    this.onReceipt?.(chart, receipt);
    return {
      resultId: receipt.dashboard_result_id,
      executionId: receipt.execution_id,
      columns: receipt.columns.map((column) => {
        const semantic = semanticColumnMetadata(receipt, column.name);
        return {
          name: column.name,
          logicalType: [
            "integer",
            "decimal",
            "numeric",
            "float",
            "money",
            "real",
          ].some((type) => column.logical_type.toLowerCase().includes(type))
            ? "number"
            : ((["string", "boolean", "date", "timestamp"].includes(
                column.logical_type,
              )
                ? column.logical_type
                : "unknown") as DashboardQueryResult["columns"][number]["logicalType"]),
          nullable: column.nullable,
          label: column.label ?? semantic.label,
          format:
            (column.format as DashboardQueryResult["columns"][number]["format"]) ??
            semantic.format,
          currencyCode: column.currency_code ?? semantic.currencyCode,
        };
      }),
      rows: receipt.rows,
      completeness: receipt.completeness,
      freshnessAt: receipt.freshness_at ?? receipt.result_time,
      timezone: this.timezone,
      locale: this.locale,
      cacheState: receipt.cache_state,
    };
  }
}
