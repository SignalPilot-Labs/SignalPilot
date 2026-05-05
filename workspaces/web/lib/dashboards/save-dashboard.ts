"use server";

import { randomUUID } from "node:crypto";
import { writeFile, rename, chmod, mkdir } from "node:fs/promises";
import { join } from "node:path";
import { getServerEnv } from "@/lib/env";
import type { DashboardDefinition } from "@/lib/dashboards/types";

export async function createDashboard(
  input: { name: string; description?: string },
): Promise<{ ok: true; id: string } | { ok: false; error: string }> {
  const env = getServerEnv();

  if (env.mode !== "local") {
    throw new Error("createDashboard is only available in local mode");
  }

  const name = input.name.trim();
  if (name.length === 0 || name.length > 120) {
    return { ok: false, error: "Name must be between 1 and 120 characters." };
  }

  const description = (input.description ?? "").trim();
  if (description.length > 500) {
    return { ok: false, error: "Description must be under 500 characters." };
  }

  const id = randomUUID();
  const now = new Date().toISOString();

  const definition: DashboardDefinition = {
    schemaVersion: 1,
    id,
    name,
    description,
    layout: { columns: 12, rowHeight: 80 },
    charts: [],
    createdAt: now,
    updatedAt: now,
  };

  const dir = env.localDashboardsDir;
  await mkdir(dir, { recursive: true });

  const finalPath = join(dir, `${id}.json`);
  const tmpPath = `${finalPath}.tmp`;

  const json = JSON.stringify(definition, null, 2);
  await writeFile(tmpPath, json, { encoding: "utf-8" });
  await rename(tmpPath, finalPath);
  await chmod(finalPath, 0o600);

  return { ok: true, id };
}
