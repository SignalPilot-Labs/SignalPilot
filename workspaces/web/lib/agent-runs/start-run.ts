"use server";

import { writeFile, rename, chmod, mkdir, rm } from "node:fs/promises";
import { join } from "node:path";
import { getServerEnv } from "@/lib/env";
import { startSession, type SandboxSessionOptions } from "@/lib/sandbox/client";

export async function startAgentRun(
  formData: FormData,
): Promise<{ ok: true; id: string } | { ok: false; error: string }> {
  const env = getServerEnv();
  if (env.mode !== "local") {
    throw new Error("startAgentRun is only available in local mode");
  }

  const raw = formData.get("prompt");
  if (typeof raw !== "string") {
    return { ok: false, error: "Prompt is required." };
  }

  const prompt = raw.trim();
  if (prompt.length === 0) {
    return { ok: false, error: "Prompt is required." };
  }
  if (prompt.length > 4000) {
    return { ok: false, error: "Prompt must be 4000 characters or fewer." };
  }

  const id = (await import("node:crypto")).randomUUID();
  const createdAt = new Date().toISOString();
  const startedAt = createdAt;

  const sessionOptions: SandboxSessionOptions = {
    model: "claude-sonnet-4-6",
    fallback_model: null,
    effort: "high",
    system_prompt: {
      type: "text",
      preset: "default",
      append:
        "You are a data analyst agent with access to SignalPilot MCP tools. " +
        "Use them to explore database schemas, run SQL queries, and build dashboards. " +
        "You can create dashboards with charts to visualize data.",
    },
    permission_mode: "bypassPermissions",
    cwd: "/home/agentuser/workdir",
    add_dirs: ["/opt/workspaces"],
    setting_sources: ["project"],
    max_budget_usd: 5.0,
    include_partial_messages: true,
    initial_prompt: prompt,
    run_id: id,
    github_repo: "",
    branch_name: "",
    mcp_servers: {
      signalpilot: { type: "http", url: env.sandboxMcpUrl },
    },
  };

  let sessionId: string;
  try {
    sessionId = await startSession(env.sandboxUrl, env.sandboxSecret, sessionOptions);
  } catch (err) {
    const msg = err instanceof Error ? err.message : String(err);
    return { ok: false, error: `Failed to start sandbox session: ${msg}` };
  }

  const manifest = {
    schemaVersion: 1,
    id,
    prompt,
    status: "running",
    createdAt,
    startedAt,
    sessionId,
  };

  await mkdir(env.localAgentRunsDir, { recursive: true });

  const finalPath = join(env.localAgentRunsDir, `${id}.json`);
  const tmpPath = join(env.localAgentRunsDir, `${id}.json.tmp`);

  try {
    await writeFile(tmpPath, JSON.stringify(manifest, null, 2), { encoding: "utf-8" });
    await rename(tmpPath, finalPath);
    await chmod(finalPath, 0o600);
  } catch (writeErr) {
    try { await rm(tmpPath, { force: true }); } catch { /* best-effort */ }
    throw writeErr;
  }

  return { ok: true, id };
}
