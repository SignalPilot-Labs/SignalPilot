import "server-only";

export type Mode = "local" | "cloud";

export type ServerEnv =
  | {
      mode: "local";
      apiUrl: string;
      localApiKey: string;
      localWorkspaceIds: string[];
      localChartsDir: string;
      localDashboardsDir: string;
      localDbtLinksDir: string;
      localAgentRunsDir: string;
      sandboxUrl: string;
      sandboxSecret: string;
      sandboxMcpUrl: string;
    }
  | { mode: "cloud"; apiUrl: string; clerkPublishableKey: string; clerkSecretKey: string };

export function getServerEnv(): ServerEnv {
  const apiUrl = required("WORKSPACES_API_URL");
  const raw = process.env["WORKSPACES_MODE"] ?? "local";
  if (raw !== "local" && raw !== "cloud") {
    throw new Error(`Invalid WORKSPACES_MODE: ${raw} (expected "local" | "cloud")`);
  }
  if (raw === "local") {
    return {
      mode: "local",
      apiUrl,
      localApiKey: required("SP_LOCAL_API_KEY"),
      localWorkspaceIds: parseCsv(process.env["WORKSPACES_LOCAL_IDS"] ?? ""),
      localChartsDir: required("WORKSPACES_LOCAL_CHARTS_DIR"),
      localDashboardsDir: required("WORKSPACES_LOCAL_DASHBOARDS_DIR"),
      localDbtLinksDir: required("WORKSPACES_LOCAL_DBT_LINKS_DIR"),
      localAgentRunsDir: required("WORKSPACES_LOCAL_AGENT_RUNS_DIR"),
      sandboxUrl: required("SANDBOX_URL"),
      sandboxSecret: required("SANDBOX_SECRET"),
      sandboxMcpUrl: required("SANDBOX_MCP_URL"),
    };
  }
  return {
    mode: "cloud",
    apiUrl,
    clerkPublishableKey: required("NEXT_PUBLIC_CLERK_PUBLISHABLE_KEY"),
    clerkSecretKey: required("CLERK_SECRET_KEY"),
  };
}

function required(name: string): string {
  const v = process.env[name];
  if (!v) throw new Error(`Missing required environment variable: ${name}`);
  return v;
}

/**
 * Parses a comma-separated list of workspace ids.
 * Each entry is trimmed; empty entries (from leading/trailing commas or double commas) are dropped.
 * Example: "ws-a, ws-b, ws-c" → ["ws-a", "ws-b", "ws-c"]
 */
function parseCsv(s: string): string[] {
  return s
    .split(",")
    .map((entry) => entry.trim())
    .filter((entry) => entry.length > 0);
}
