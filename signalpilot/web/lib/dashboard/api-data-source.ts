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

export class DashboardApiDataSource implements DashboardDataSource {
  constructor(
    private readonly dashboardId: string,
    private readonly versionId: string,
    private readonly onReceipt?: (
      chart: ChartDefinition,
      receipt: DashboardQueryReceipt,
    ) => void,
  ) {}

  async loadTile(
    tile: DashboardTileDefinition,
    chart: ChartDefinition,
    options: DashboardQueryOptions,
    signal: AbortSignal,
  ): Promise<DashboardQueryResult> {
    const receipt = await request<DashboardQueryReceipt>(
      `/api/dashboards/${this.dashboardId}/charts/${chart.id}/query`,
      {
        method: "POST",
        body: JSON.stringify({
          version_id: this.versionId,
          tile_uuid: tile.uuid,
          refresh: options.invalidateCache ?? false,
          dashboard_filters: options.dashboardFilters ?? [],
          drill_path: (options.dashboardDrillPath ?? []).map((step) => ({
            field_id: step.fieldId,
            value: step.value,
          })),
        }),
        signal,
      },
    );
    this.onReceipt?.(chart, receipt);
    return {
      resultId: receipt.dashboard_result_id,
      executionId: receipt.execution_id,
      columns: receipt.columns.map((column) => ({
        name: column.name,
        logicalType:
          column.logical_type === "integer"
            ? "number"
            : (column.logical_type as DashboardQueryResult["columns"][number]["logicalType"]),
        nullable: column.nullable,
      })),
      rows: receipt.rows,
      completeness: receipt.completeness,
      freshnessAt: receipt.freshness_at ?? receipt.result_time,
      cacheState: receipt.cache_state,
    };
  }
}
