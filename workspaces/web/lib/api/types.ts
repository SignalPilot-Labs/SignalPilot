export type ChartType = "line" | "bar" | "table" | "number";

export interface ChartQueryResponse {
  id: string;
  chart_id: string;
  connector_name: string;
  sql: string;
  params: Record<string, unknown>;
  refresh_interval_seconds: number;
  created_at: string;
}

export interface ChartResponse {
  id: string;
  workspace_id: string;
  title: string;
  chart_type: ChartType;
  echarts_option_json: Record<string, unknown>;
  created_at: string;
  updated_at: string;
  created_by: string | null;
  query: ChartQueryResponse | null;
}

export interface ChartListResponse {
  items: ChartResponse[];
  next_cursor: string | null;
}

export interface ChartRunResponse {
  chart_id: string;
  cache_key: string;
  cached: boolean;
  computed_at: string;
  columns: { name: string; type: string }[];
  rows: unknown[][];
  truncated: boolean;
}

export class ApiError extends Error {
  status: number;
  code: string;

  constructor(status: number, code: string, message: string) {
    super(message);
    this.name = "ApiError";
    this.status = status;
    this.code = code;
  }
}
