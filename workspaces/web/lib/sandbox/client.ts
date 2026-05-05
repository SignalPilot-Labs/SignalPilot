import "server-only";

export interface SandboxSessionOptions {
  model: string;
  fallback_model: string | null;
  effort: string;
  system_prompt: { type: string; preset: string; append: string };
  permission_mode: string;
  cwd: string;
  add_dirs: string[];
  setting_sources: string[];
  max_budget_usd: number;
  include_partial_messages: boolean;
  initial_prompt: string;
  run_id: string;
  github_repo: string;
  branch_name: string;
  mcp_servers: Record<string, { type: string; url: string }>;
}

export async function startSession(
  sandboxUrl: string,
  secret: string,
  options: SandboxSessionOptions,
): Promise<string> {
  const res = await fetch(`${sandboxUrl}/session/start`, {
    method: "POST",
    headers: {
      "Content-Type": "application/json",
      "X-Internal-Secret": secret,
    },
    body: JSON.stringify(options),
  });
  if (!res.ok) {
    const text = await res.text().catch(() => "");
    throw new Error(`Sandbox session/start failed (${res.status}): ${text}`);
  }
  const data = await res.json();
  return data.session_id as string;
}

export async function stopSession(
  sandboxUrl: string,
  secret: string,
  sessionId: string,
): Promise<void> {
  await fetch(`${sandboxUrl}/session/${sessionId}/stop`, {
    method: "POST",
    headers: { "X-Internal-Secret": secret },
  });
}
