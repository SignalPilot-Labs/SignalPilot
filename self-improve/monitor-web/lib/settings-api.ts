import type { SettingsStatus, Settings } from "./types";

function getApiBase(): string {
  if (typeof window === "undefined") return "http://localhost:3401";
  return "";
}

export async function fetchSettingsStatus(): Promise<SettingsStatus> {
  try {
    const res = await fetch(`${getApiBase()}/api/settings/status`);
    if (!res.ok) throw new Error("Failed to fetch settings status");
    return res.json();
  } catch {
    return { configured: false, has_claude_token: false, has_git_token: false, has_github_repo: false };
  }
}

export async function fetchSettings(): Promise<Settings> {
  const res = await fetch(`${getApiBase()}/api/settings`);
  if (!res.ok) throw new Error("Failed to fetch settings");
  return res.json();
}

export async function updateSettings(
  settings: Partial<Settings>
): Promise<{ ok: boolean; updated: string[] }> {
  const res = await fetch(`${getApiBase()}/api/settings`, {
    method: "PUT",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(settings),
  });
  if (!res.ok) throw new Error("Failed to update settings");
  return res.json();
}
