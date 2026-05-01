import "server-only";

import { readdir, readFile } from "node:fs/promises";
import { join } from "node:path";
import { getServerEnv } from "@/lib/env";
import { LINK_KINDS, type DbtLinkV1 } from "@/lib/dbt-links/types";

export function isDbtLinkV1(v: unknown): v is DbtLinkV1 {
  if (typeof v !== "object" || v === null) return false;
  const obj = v as Record<string, unknown>;
  // schemaVersion === 1 is a hard requirement; any other version is rejected
  if (obj.schemaVersion !== 1) return false;
  if (typeof obj.id !== "string") return false;
  if (typeof obj.name !== "string") return false;
  if (typeof obj.kind !== "string") return false;
  if (typeof obj.createdAt !== "string") return false;
  if (typeof obj.relativePath !== "string") return false;
  if (!LINK_KINDS.includes(obj.kind as (typeof LINK_KINDS)[number])) return false;
  return true;
}

export async function loadDbtLinks(): Promise<DbtLinkV1[]> {
  const env = getServerEnv();
  if (env.mode !== "local") {
    throw new Error("loadDbtLinks is only available in local mode");
  }

  const dir = env.localDbtLinksDir;

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
    jsonFiles.map(async (filename): Promise<DbtLinkV1 | null> => {
      const filepath = join(dir, filename);
      try {
        const raw = await readFile(filepath, "utf-8");
        const parsed: unknown = JSON.parse(raw);
        if (!isDbtLinkV1(parsed)) {
          console.warn(`load-links: skipping malformed file ${filename}`);
          return null;
        }
        return parsed;
      } catch {
        console.warn(`load-links: skipping unreadable/unparseable file ${filename}`);
        return null;
      }
    }),
  );

  const links = results.filter((l): l is DbtLinkV1 => l !== null);

  // ISO 8601 strings lex-sort correctly; descending = b before a
  return links.sort((a, b) => b.createdAt.localeCompare(a.createdAt));
}
