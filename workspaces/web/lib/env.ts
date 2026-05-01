import "server-only";

export interface ServerEnv {
  apiUrl: string;
  localApiKey: string;
}

export function getServerEnv(): ServerEnv {
  const apiUrl = process.env["WORKSPACES_API_URL"];
  if (!apiUrl) {
    throw new Error(
      "Missing required environment variable: WORKSPACES_API_URL"
    );
  }

  const localApiKey = process.env["SP_LOCAL_API_KEY"];
  if (!localApiKey) {
    throw new Error(
      "Missing required environment variable: SP_LOCAL_API_KEY"
    );
  }

  return { apiUrl, localApiKey };
}
