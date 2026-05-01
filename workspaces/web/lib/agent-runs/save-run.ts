"use server";

import { writeFile, rename, chmod, mkdir, rm } from "node:fs/promises";
import { join } from "node:path";
import { getServerEnv } from "@/lib/env";

export async function saveAgentRun(
  formData: FormData,
): Promise<{ ok: true; id: string } | { ok: false; error: string }> {
  // Step 1: mode gate — throws on cloud, no catch swallow.
  const env = getServerEnv();
  if (env.mode !== "local") {
    throw new Error("saveAgentRun is only available in local mode");
  }

  // Step 2: validate prompt.
  const raw = formData.get("prompt");
  if (typeof raw !== "string") {
    return { ok: false, error: "Prompt is required." };
  }

  // Step 3: trim.
  const prompt = raw.trim();

  // Step 4: empty check.
  if (prompt.length === 0) {
    return { ok: false, error: "Prompt is required." };
  }

  // Step 5: length cap.
  if (prompt.length > 4000) {
    return { ok: false, error: "Prompt must be 4000 characters or fewer." };
  }

  // Step 6: generate server-side ID — NEVER trust client.
  const id = (await import("node:crypto")).randomUUID();

  // Step 7: timestamp.
  const createdAt = new Date().toISOString();

  // Step 8: build manifest.
  const manifest = { schemaVersion: 1, id, prompt, status: "pending", createdAt };

  // Step 9: ensure parent dir exists.
  await mkdir(env.localAgentRunsDir, { recursive: true });

  // Step 10: atomic write — tmp → rename → chmod 0o600.
  const finalPath = join(env.localAgentRunsDir, `${id}.json`);
  const tmpPath = join(env.localAgentRunsDir, `${id}.json.tmp`);

  try {
    await writeFile(tmpPath, JSON.stringify(manifest, null, 2), { encoding: "utf-8" });
    await rename(tmpPath, finalPath);
    await chmod(finalPath, 0o600);
  } catch (writeErr) {
    // Best-effort cleanup of tmp file; swallow cleanup error so real error is not masked.
    try {
      await rm(tmpPath, { force: true });
    } catch (cleanupErr) {
      console.error(`saveAgentRun: cleanup of tmp file failed for id=${id}:`, cleanupErr);
    }
    throw writeErr;
  }

  // Step 11: success.
  return { ok: true, id };
}
