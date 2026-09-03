import { request } from "~/lib/api";
import type {
  ChartDefinition,
  DashboardDataSource,
  DashboardFailure,
  DashboardFailureCode,
  DashboardQueryOptions,
  DashboardQueryResult,
  DashboardResultState,
  DashboardTileDefinition,
} from "~/lib/dashboard/contracts";

type DashboardFailurePayload = {
  code: DashboardFailureCode;
  message: string;
  retryable: boolean;
  connection_name?: string | null;
  scope: DashboardFailure["scope"];
  correlation_id: string;
  occurred_at: string;
  cache_fallback_available?: boolean;
  cache_state?: "no_usable_cache";
  retry_after_seconds?: number | null;
};

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
  connection_type?: string | null;
  cache_state: DashboardResultState;
  refresh_failure?: DashboardFailurePayload | null;
};

const FAILURE_MESSAGES: Record<DashboardFailureCode, string> = {
  data_source_unavailable: "The data source is temporarily unavailable.",
  authentication_rejected: "The data source rejected its saved credentials.",
  query_timeout: "The data source did not finish the query in time.",
  query_invalid: "This chart query is no longer valid for the data source.",
  semantic_definition_invalid:
    "This chart's semantic definition is no longer valid.",
  permission_denied: "You do not have permission to query this dashboard data.",
  rate_limited: "Dashboard queries are temporarily rate limited.",
  cancelled: "The dashboard query was cancelled.",
  result_contract_mismatch:
    "The returned data does not match this chart's expected fields.",
  stale_dashboard_version: "This dashboard version is no longer current.",
  internal_error: "SignalPilot could not complete this dashboard query.",
};

const FAILURE_CODES = new Set<DashboardFailureCode>(
  Object.keys(FAILURE_MESSAGES) as DashboardFailureCode[],
);

function correlationId(): string {
  return globalThis.crypto?.randomUUID?.() ?? `dashboard-${Date.now()}`;
}

function failureFromPayload(
  payload: DashboardFailurePayload,
  connectionName?: string,
): DashboardFailure {
  return {
    code: payload.code,
    message: FAILURE_MESSAGES[payload.code],
    retryable: payload.retryable,
    connectionName: payload.connection_name ?? connectionName,
    scope: payload.scope,
    correlationId: payload.correlation_id,
    occurredAt: payload.occurred_at,
    cacheFallbackAvailable: payload.cache_fallback_available ?? false,
    cacheState: payload.cache_state,
    retryAfterSeconds: payload.retry_after_seconds ?? undefined,
  };
}

function fallbackFailure(
  code: DashboardFailureCode,
  connectionName?: string,
): DashboardFailure {
  const connectionScope = [
    "data_source_unavailable",
    "authentication_rejected",
    "query_timeout",
    "rate_limited",
  ].includes(code);
  return {
    code,
    message: FAILURE_MESSAGES[code],
    retryable: [
      "data_source_unavailable",
      "query_timeout",
      "rate_limited",
      "internal_error",
    ].includes(code),
    connectionName,
    scope: connectionScope
      ? "connection"
      : [
            "permission_denied",
            "stale_dashboard_version",
            "internal_error",
          ].includes(code)
        ? "dashboard"
        : "chart",
    correlationId: correlationId(),
    occurredAt: new Date().toISOString(),
    cacheFallbackAvailable: false,
    cacheState: "no_usable_cache",
  };
}

export class DashboardQueryError extends Error {
  constructor(readonly failure: DashboardFailure) {
    super(failure.message);
    this.name = "DashboardQueryError";
  }
}

export function dashboardFailureFromCause(
  cause: unknown,
  connectionName?: string,
): DashboardFailure {
  if (cause instanceof DashboardQueryError) return cause.failure;
  const message = cause instanceof Error ? cause.message : "";
  const response = /^(\d{3}):\s*([\s\S]*)$/.exec(message);
  if (response) {
    const status = Number(response[1]);
    try {
      const parsed = JSON.parse(response[2]) as {
        detail?: DashboardFailurePayload;
      };
      if (
        parsed.detail &&
        typeof parsed.detail === "object" &&
        FAILURE_CODES.has(parsed.detail.code)
      ) {
        return failureFromPayload(parsed.detail, connectionName);
      }
    } catch {
      // Fall through to the status-only safe taxonomy.
    }
    const code: DashboardFailureCode =
      status === 401 || status === 403
        ? "permission_denied"
        : status === 409
          ? "stale_dashboard_version"
          : status === 429
            ? "rate_limited"
            : status === 422
              ? "semantic_definition_invalid"
              : status === 502
                ? "result_contract_mismatch"
                : status === 503
                  ? "data_source_unavailable"
                  : status === 504
                    ? "query_timeout"
                    : "internal_error";
    return fallbackFailure(code, connectionName);
  }
  if (/abort|cancel/i.test(message))
    return fallbackFailure("cancelled", connectionName);
  if (/failed to fetch|networkerror|load failed/i.test(message))
    return fallbackFailure("data_source_unavailable", connectionName);
  return fallbackFailure("internal_error", connectionName);
}

export function isUnsafeTruncatedSeriesError(cause: unknown): boolean {
  return (
    cause instanceof DashboardQueryError &&
    cause.failure.code === "result_contract_mismatch"
  );
}

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
    private readonly connectionName?: string,
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
    let receipt: DashboardQueryReceipt;
    try {
      receipt = await request<DashboardQueryReceipt>(queryPath, {
        method: "POST",
        body: JSON.stringify({
          version_id: this.versionId,
          authoring_session_id: this.authoringSessionId,
          tile_uuid: tile.uuid,
          refresh: options.invalidateCache ?? false,
          retry_token: options.retryToken,
          dashboard_filters: options.dashboardFilters ?? [],
          drill_path: (options.dashboardDrillPath ?? []).map((step) => ({
            field_id: step.fieldId,
            value: step.value,
          })),
        }),
        signal,
      });
    } catch (cause) {
      throw new DashboardQueryError(
        dashboardFailureFromCause(cause, this.connectionName),
      );
    }
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
      refreshFailure: receipt.refresh_failure
        ? failureFromPayload(receipt.refresh_failure, this.connectionName)
        : undefined,
    };
  }
}
