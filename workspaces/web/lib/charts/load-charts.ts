import "server-only";

import { readdir, readFile } from "node:fs/promises";
import { join } from "node:path";
import { getServerEnv } from "@/lib/env";
import { CHART_TYPES, type ChartDefinitionV1 } from "@/lib/charts/types";

const UUID_V4_REGEX = /^[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/i;

function isChartDefinitionV1(value: unknown): value is ChartDefinitionV1 {
  if (typeof value !== "object" || value === null) return false;
  const v = value as Record<string, unknown>;
  // schemaVersion === 1 is a hard requirement; any other version is rejected
  if (v.schemaVersion !== 1) return false;
  if (typeof v.id !== "string") return false;
  if (typeof v.name !== "string") return false;
  if (typeof v.type !== "string") return false;
  if (typeof v.sql !== "string") return false;
  if (typeof v.createdAt !== "string") return false;
  if (!CHART_TYPES.includes(v.type as (typeof CHART_TYPES)[number])) return false;
  return true;
}

export async function loadChartDefinitions(): Promise<ChartDefinitionV1[]> {
  const env = getServerEnv();
  if (env.mode !== "local") {
    throw new Error("loadChartDefinitions is only available in local mode");
  }

  const dir = env.localChartsDir;

  let entries: string[];
  try {
    entries = await readdir(dir);
  } catch (err) {
    if ((err as NodeJS.ErrnoException).code === "ENOENT") {
      return [];
    }
    throw err;
  }

  // Filter to exact *.json, skipping *.json.tmp (race condition from atomic writes)
  const jsonFiles = entries.filter((name) => /\.json$/.test(name) && !/\.json\.tmp$/.test(name));

  const results = await Promise.all(
    jsonFiles.map(async (filename): Promise<ChartDefinitionV1 | null> => {
      const filepath = join(dir, filename);
      try {
        const raw = await readFile(filepath, "utf-8");
        const parsed: unknown = JSON.parse(raw);
        if (!isChartDefinitionV1(parsed)) {
          console.warn(`load-charts: skipping malformed file ${filename}`);
          return null;
        }
        return parsed;
      } catch {
        console.warn(`load-charts: skipping unreadable/unparseable file ${filename}`);
        return null;
      }
    }),
  );

  const definitions = results.filter((d): d is ChartDefinitionV1 => d !== null);

  // ISO 8601 strings lex-sort correctly; descending = b before a
  return definitions.sort((a, b) => b.createdAt.localeCompare(a.createdAt));
}

export async function loadChartDefinition(id: string): Promise<ChartDefinitionV1 | null> {
  const env = getServerEnv();
  if (env.mode !== "local") {
    throw new Error("loadChartDefinition is only available in local mode");
  }

  if (!UUID_V4_REGEX.test(id)) {
    return null;
  }

  const filepath = join(env.localChartsDir, `${id}.json`);

  let raw: string;
  try {
    raw = await readFile(filepath, "utf-8");
  } catch (err) {
    if ((err as NodeJS.ErrnoException).code === "ENOENT") {
      return null;
    }
    throw err;
  }

  let parsed: unknown;
  try {
    parsed = JSON.parse(raw);
  } catch {
    return null;
  }

  if (!isChartDefinitionV1(parsed)) {
    return null;
  }

  return parsed;
}
