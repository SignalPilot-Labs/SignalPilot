"use server";

import { randomUUID } from "node:crypto";
import { writeFile, rename, chmod, mkdir } from "node:fs/promises";
import { join } from "node:path";
import { getServerEnv } from "@/lib/env";
import { CHART_TYPES, type ChartDraft, type ChartDefinitionV1 } from "@/lib/charts/types";

export async function saveChartDefinition(
  input: ChartDraft,
): Promise<{ ok: true; id: string } | { ok: false; error: string }> {
  const env = getServerEnv();

  if (env.mode !== "local") {
    throw new Error("saveChartDefinition is only available in local mode");
  }

  const name = input.name.trim();
  if (name.length === 0 || name.length > 120) {
    return { ok: false, error: "Name must be between 1 and 120 characters." };
  }

  if (!CHART_TYPES.includes(input.type as (typeof CHART_TYPES)[number])) {
    return { ok: false, error: `Invalid chart type: ${input.type}` };
  }

  const sql = input.sql.trim();
  if (sql.length === 0 || sql.length > 4000) {
    return { ok: false, error: "SQL must be between 1 and 4000 characters." };
  }

  const id = randomUUID();
  const createdAt = new Date().toISOString();

  const definition: ChartDefinitionV1 = {
    schemaVersion: 1,
    id,
    name,
    type: input.type,
    sql,
    createdAt,
  };

  const localChartsDir = env.localChartsDir;
  await mkdir(localChartsDir, { recursive: true });

  const finalPath = join(localChartsDir, `${id}.json`);
  const tmpPath = `${finalPath}.tmp`;

  const json = JSON.stringify(definition, null, 2);
  await writeFile(tmpPath, json, { encoding: "utf-8" });
  await rename(tmpPath, finalPath);
  await chmod(finalPath, 0o600);

  return { ok: true, id };
}
