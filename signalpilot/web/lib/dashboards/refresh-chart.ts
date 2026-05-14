"use server";

import { readFile, writeFile, rename } from "node:fs/promises";
import { join } from "node:path";
import type { DashboardDefinition, CachedData } from "./types";

function getDashboardsDir(): string {
  const dir = process.env.SP_DASHBOARDS_DIR;
  if (!dir) throw new Error("Missing SP_DASHBOARDS_DIR environment variable");
  return dir;
}

function getGatewayUrl(): string {
  return (
    process.env.GATEWAY_INTERNAL_URL ||
    process.env.NEXT_PUBLIC_GATEWAY_URL ||
    "http://localhost:3300"
  );
}

function getApiKey(): string {
  const key = process.env.SP_LOCAL_API_KEY;
  if (!key) throw new Error("Missing SP_LOCAL_API_KEY");
  return key;
}

async function executeChartSql(
  connectionName: string,
  sql: string,
): Promise<CachedData> {
  const res = await fetch(`${getGatewayUrl()}/api/query`, {
    method: "POST",
    headers: {
      "Content-Type": "application/json",
      Authorization: `Bearer ${getApiKey()}`,
    },
    body: JSON.stringify({
      connection_name: connectionName,
      sql,
      row_limit: 500,
      timeout_seconds: 60,
    }),
  });

  if (!res.ok) {
    const body = await res.text();
    throw new Error(`Query failed (${res.status}): ${body}`);
  }

  const data = await res.json();
  const rows: Record<string, unknown>[] = data.rows ?? [];

  if (rows.length === 0) {
    return { columns: [], rows: [], computedAt: new Date().toISOString() };
  }

  const columns = Object.keys(rows[0]).map((name) => ({ name, type: "text" }));
  const dataRows = rows.map((row) => columns.map((col) => row[col.name] ?? null));

  return {
    columns,
    rows: dataRows,
    computedAt: new Date().toISOString(),
  };
}

async function loadAndParseDashboard(id: string): Promise<DashboardDefinition> {
  const filepath = join(getDashboardsDir(), `${id}.json`);
  const raw = await readFile(filepath, "utf-8");
  return JSON.parse(raw) as DashboardDefinition;
}

async function saveDashboard(dashboard: DashboardDefinition): Promise<void> {
  const dir = getDashboardsDir();
  const finalPath = join(dir, `${dashboard.id}.json`);
  const tmpPath = `${finalPath}.tmp`;
  await writeFile(tmpPath, JSON.stringify(dashboard, null, 2), "utf-8");
  await rename(tmpPath, finalPath);
}

export async function refreshChart(
  dashboardId: string,
  chartId: string,
): Promise<{ ok: true } | { ok: false; error: string }> {
  try {
    const dashboard = await loadAndParseDashboard(dashboardId);
    const chart = dashboard.charts.find((c) => c.id === chartId);
    if (!chart) return { ok: false, error: "Chart not found" };

    chart.cachedData = await executeChartSql(chart.connectionName, chart.sql);
    dashboard.updatedAt = new Date().toISOString();
    await saveDashboard(dashboard);
    return { ok: true };
  } catch (e) {
    return { ok: false, error: e instanceof Error ? e.message : String(e) };
  }
}

export async function refreshAllCharts(
  dashboardId: string,
): Promise<{ ok: true; refreshed: number; failed: number } | { ok: false; error: string }> {
  try {
    const dashboard = await loadAndParseDashboard(dashboardId);
    let refreshed = 0;
    let failed = 0;

    await Promise.all(
      dashboard.charts.map(async (chart) => {
        try {
          chart.cachedData = await executeChartSql(chart.connectionName, chart.sql);
          refreshed++;
        } catch {
          failed++;
        }
      }),
    );

    dashboard.updatedAt = new Date().toISOString();
    await saveDashboard(dashboard);
    return { ok: true, refreshed, failed };
  } catch (e) {
    return { ok: false, error: e instanceof Error ? e.message : String(e) };
  }
}
