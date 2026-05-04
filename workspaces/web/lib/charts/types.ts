export const CHART_TYPES = ["bar", "line", "table", "kpi"] as const;
export type ChartType = (typeof CHART_TYPES)[number];

export interface ChartDraft {
  name: string; // 1..120 chars, trimmed
  type: ChartType;
  sql: string; // 1..4000 chars, trimmed
}

export interface ChartDefinitionV1 {
  schemaVersion: 1;
  id: string; // crypto.randomUUID()
  name: string;
  type: ChartType;
  sql: string;
  createdAt: string; // ISO 8601 UTC
}
