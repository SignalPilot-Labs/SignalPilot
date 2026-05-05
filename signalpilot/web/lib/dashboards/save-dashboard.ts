"use server";

import { randomUUID } from "node:crypto";
import { writeFile, rename, mkdir } from "node:fs/promises";
import { join } from "node:path";
import type { DashboardDefinition } from "./types";

function getDashboardsDir(): string {
  const dir = process.env.SP_DASHBOARDS_DIR;
  if (!dir) throw new Error("Missing SP_DASHBOARDS_DIR environment variable");
  return dir;
}

export async function createDashboard(
  input: { name: string; description?: string },
): Promise<{ ok: true; id: string } | { ok: false; error: string }> {
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

  const dir = getDashboardsDir();
  await mkdir(dir, { recursive: true });

  const finalPath = join(dir, `${id}.json`);
  const tmpPath = `${finalPath}.tmp`;

  const json = JSON.stringify(definition, null, 2);
  await writeFile(tmpPath, json, { encoding: "utf-8" });
  await rename(tmpPath, finalPath);

  return { ok: true, id };
}
