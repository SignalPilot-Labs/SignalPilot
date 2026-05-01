import "server-only";

export type Mode = "local" | "cloud";

export type ServerEnv =
  | { mode: "local"; apiUrl: string; localApiKey: string }
  | { mode: "cloud"; apiUrl: string; clerkPublishableKey: string; clerkSecretKey: string };

export function getServerEnv(): ServerEnv {
  const apiUrl = required("WORKSPACES_API_URL");
  const raw = process.env["WORKSPACES_MODE"] ?? "local";
  if (raw !== "local" && raw !== "cloud") {
    throw new Error(`Invalid WORKSPACES_MODE: ${raw} (expected "local" | "cloud")`);
  }
  if (raw === "local") {
    return { mode: "local", apiUrl, localApiKey: required("SP_LOCAL_API_KEY") };
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
