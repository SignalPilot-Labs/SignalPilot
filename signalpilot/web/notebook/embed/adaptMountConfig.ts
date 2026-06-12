import type { AuthTokenProvider } from "@/core/runtime/types";
import type { SignalpilotClient, SignalpilotMountConfig } from "./types";

/**
 * Single chokepoint for building the raw options blob that is fed into
 * `mountOptionsSchema.safeParse()` via `initStore`.
 *
 * Embed callers must always pass config explicitly. The standalone boot path
 * fetches mount config via `GET /api/mount-config` and calls `mount()` directly.
 *
 * The `mode` field is injected here (not in `SignalpilotMountConfig`) because
 * the schema requires it and embed components own the correct value.
 */
export function adaptMountConfig(source: {
  config: SignalpilotMountConfig;
  client: SignalpilotClient;
  mode: "edit" | "home";
}): unknown {
  const { config, client, mode } = source;

  // Build the options blob. Map SignalpilotMountConfig fields to the
  // mountOptionsSchema shape. The schema requires `mode` — inject it here.
  return {
    mode,
    filename: config.filename,
    code: config.initialCode,
    session: config.session,
    notebook: config.notebook,
    version: config.version,
    config: config.userConfig,
    appConfig: config.appConfig,
    configOverrides: config.configOverrides,
    serverToken: config.serverToken ?? client.options.serverToken,
    runtimeConfig: buildRuntimeConfig(config, client),
    gatewayUrl: config.gatewayUrl,
    gatewayApiKey: config.gatewayApiKey,
  };
}

function buildRuntimeConfig(
  config: SignalpilotMountConfig,
  client: SignalpilotClient,
): Array<{ url: string; authToken?: AuthTokenProvider; lazy?: boolean }> {
  // Props-level runtimeConfig takes precedence over client-level.
  if (config.runtimeConfig && config.runtimeConfig.length > 0) {
    return config.runtimeConfig;
  }
  if (client.options.runtimeConfig) {
    return [client.options.runtimeConfig];
  }
  return [];
}
