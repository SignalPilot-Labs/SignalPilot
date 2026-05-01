import "server-only";

import { readdir, readFile } from "node:fs/promises";
import { join } from "node:path";
import { getServerEnv } from "@/lib/env";
import { AGENT_RUN_STATUSES, type AgentRunV1 } from "@/lib/agent-runs/types";

const UUID_V4_REGEX =
  /^[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/i;

const OPTIONAL_STRING_FIELDS: ReadonlyArray<keyof AgentRunV1> = [
  "startedAt",
  "finishedAt",
  "errorMessage",
  "summary",
  "pendingApproval",
  "targetWorkspaceId",
];

export function isAgentRunV1(v: unknown): v is AgentRunV1 {
  if (typeof v !== "object" || v === null) return false;
  const obj = v as Record<string, unknown>;
  if (obj.schemaVersion !== 1) return false;
  if (typeof obj.id !== "string") return false;
  if (typeof obj.prompt !== "string") return false;
  if (typeof obj.status !== "string") return false;
  if (typeof obj.createdAt !== "string") return false;
  if (!AGENT_RUN_STATUSES.includes(obj.status as (typeof AGENT_RUN_STATUSES)[number])) return false;
  // Optional string fields — when present must be strings (not null, not number)
  for (const field of OPTIONAL_STRING_FIELDS) {
    if (field in obj && obj[field] !== undefined && typeof obj[field] !== "string") return false;
  }
  return true;
}

export async function loadAgentRuns(): Promise<AgentRunV1[]> {
  const env = getServerEnv();
  if (env.mode !== "local") {
    throw new Error("loadAgentRuns is only available in local mode");
  }

  const dir = env.localAgentRunsDir;

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
    jsonFiles.map(async (filename): Promise<AgentRunV1 | null> => {
      const filepath = join(dir, filename);
      try {
        const raw = await readFile(filepath, "utf-8");
        const parsed: unknown = JSON.parse(raw);
        if (!isAgentRunV1(parsed)) {
          console.warn(`load-runs: skipping malformed file ${filename}`);
          return null;
        }
        return parsed;
      } catch {
        console.warn(`load-runs: skipping unreadable/unparseable file ${filename}`);
        return null;
      }
    }),
  );

  const runs = results.filter((r): r is AgentRunV1 => r !== null);

  // ISO 8601 strings lex-sort correctly; descending = b before a
  return runs.sort((a, b) => b.createdAt.localeCompare(a.createdAt));
}

export async function loadAgentRun(id: string): Promise<AgentRunV1 | null> {
  const env = getServerEnv();
  if (env.mode !== "local") {
    throw new Error("loadAgentRun is only available in local mode");
  }

  if (!UUID_V4_REGEX.test(id)) {
    return null;
  }

  const filepath = join(env.localAgentRunsDir, `${id}.json`);

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

  if (!isAgentRunV1(parsed)) {
    return null;
  }

  return parsed;
}
