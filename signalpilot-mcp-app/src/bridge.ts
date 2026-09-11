import { App, type McpUiDisplayMode } from "@modelcontextprotocol/ext-apps";

export const app = new App({ name: "SignalPilot Pulse", version: "1.0.0" }, {});

export async function callTool<T>(name: string, args: Record<string, unknown>): Promise<T> {
  const result = await app.callServerTool({ name, arguments: args });
  if (result.isError) {
    const lines = result.content
      .filter((item) => item.type === "text")
      .map((item) => item.text);
    const data = result.structuredContent as Record<string, unknown> | undefined;
    const details = [...lines, data?.error].filter((item): item is string => typeof item === "string" && item.length > 0);
    const message = [...new Set(details)].join("\n") || `${name} failed`;
    throw new Error(message.length > 600 ? `${message.slice(0, 600)}…` : message);
  }
  if (!result.structuredContent) throw new Error(`${name} returned no data`);
  return result.structuredContent as T;
}

/**
 * What this host lets the panel do. The panel is read-only by design: it
 * never opens links or sends messages, so the only ability it asks about is
 * which display modes exist.
 */
export type HostAbilities = {
  displayModes: McpUiDisplayMode[];
};

export function hostAbilities(): HostAbilities {
  return { displayModes: app.getHostContext()?.availableDisplayModes ?? [] };
}

export async function requestDisplayMode(mode: McpUiDisplayMode): Promise<McpUiDisplayMode | null> {
  try {
    const result = await app.requestDisplayMode({ mode });
    return result.mode;
  } catch {
    return null;
  }
}
