import "server-only";

import { readdir, readFile } from "node:fs/promises";
import { join } from "node:path";
import { DASHBOARD_CHART_TYPES, type DashboardDefinition } from "./types";

const UUID_RE = /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i;

function isDashboardDefinition(value: unknown): value is DashboardDefinition {
  if (typeof value !== "object" || value === null) return false;
  const v = value as Record<string, unknown>;
  if (v.schemaVersion !== 1) return false;
  if (typeof v.id !== "string") return false;
  if (typeof v.name !== "string") return false;
  if (typeof v.createdAt !== "string") return false;
  if (typeof v.updatedAt !== "string") return false;
  if (!Array.isArray(v.charts)) return false;
  for (const chart of v.charts) {
    if (typeof chart !== "object" || chart === null) return false;
    const c = chart as Record<string, unknown>;
    if (typeof c.id !== "string") return false;
    if (typeof c.chartType !== "string") return false;
    if (!DASHBOARD_CHART_TYPES.includes(c.chartType as (typeof DASHBOARD_CHART_TYPES)[number]))
      return false;
  }
  return true;
}

function getDashboardsDir(): string {
  const dir = process.env.SP_DASHBOARDS_DIR;
  if (!dir) throw new Error("Missing SP_DASHBOARDS_DIR environment variable");
  return dir;
}

export async function loadDashboards(): Promise<DashboardDefinition[]> {
  const dir = getDashboardsDir();

  let entries: string[];
  try {
    entries = await readdir(dir);
  } catch (err) {
    if ((err as NodeJS.ErrnoException).code === "ENOENT") {
      return [];
    }
    throw err;
  }

  const jsonFiles = entries.filter((name) => /\.json$/.test(name) && !/\.json\.tmp$/.test(name));

  const results = await Promise.all(
    jsonFiles.map(async (filename): Promise<DashboardDefinition | null> => {
      const filepath = join(dir, filename);
      try {
        const raw = await readFile(filepath, "utf-8");
        const parsed: unknown = JSON.parse(raw);
        if (!isDashboardDefinition(parsed)) {
          console.warn(`load-dashboards: skipping malformed file ${filename}`);
          return null;
        }
        return parsed;
      } catch {
        console.warn(`load-dashboards: skipping unreadable file ${filename}`);
        return null;
      }
    }),
  );

  const dashboards = results.filter((d): d is DashboardDefinition => d !== null);
  return dashboards.sort((a, b) => b.updatedAt.localeCompare(a.updatedAt));
}

export async function loadDashboard(id: string): Promise<DashboardDefinition | null> {
  if (!UUID_RE.test(id)) return null;

  const dir = getDashboardsDir();
  const filepath = join(dir, `${id}.json`);

  let raw: string;
  try {
    raw = await readFile(filepath, "utf-8");
  } catch (err) {
    if ((err as NodeJS.ErrnoException).code === "ENOENT") return null;
    throw err;
  }

  let parsed: unknown;
  try {
    parsed = JSON.parse(raw);
  } catch {
    return null;
  }

  if (!isDashboardDefinition(parsed)) return null;
  return parsed;
}
