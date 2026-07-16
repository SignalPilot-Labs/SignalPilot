import type * as api from "@/packages/sp-api";
import { z } from "zod";
import {
  appConfigAtom,
  configOverridesAtom,
  userConfigAtom,
} from "@/core/config/config";
import {
  parseAppConfig,
  parseConfigOverrides,
  parseUserConfig,
} from "@/core/config/config-schema";
import { KnownQueryParams } from "@/core/constants";
import { getSpCode } from "@/core/meta/globals";
import {
  gatewayApiKeyAtom,
  gatewayUrlAtom,
  rawFallbackAtom,
  serverTokenAtom,
  showCodeInRunModeAtom,
  spVersionAtom,
} from "@/core/meta/state";
import { type AppMode, initModeRouter, viewStateAtom } from "@/core/mode";
import { connectionAtom } from "@/core/network/connection";
import { requestClientAtom } from "@/core/network/requests";
import { resolveRequestClient } from "@/core/network/resolve";
import {
  DEFAULT_RUNTIME_CONFIG,
  runtimeConfigAtom,
} from "@/core/runtime/config";
import {
  codeAtom,
  cwdAtom,
  filenameAtom,
  lspWorkspaceAtom,
} from "@/core/saving/file-state";
import { store, type JotaiStore } from "@/core/state/jotai";
import { isStaticNotebook } from "@/core/static/static-state";
import { WebSocketState } from "@/core/websocket/types";
import { Logger } from "@/utils/Logger";

const passthroughObject = z
  .looseObject({})
  .nullish()
  .default({})
  .transform((val) => {
    if (val) {
      return val;
    }
    if (typeof val === "string") {
      Logger.warn(
        "[sp] received JSON string instead of object. Parsing...",
      );
      return JSON.parse(val);
    }
    Logger.warn("[sp] missing config data");
    return {};
  });

// This should be extremely backwards compatible and require no options.
export const mountOptionsSchema = z.object({
  filename: z
    .string()
    .nullish()
    .transform((val) => val ?? null),
  cwd: z.string().nullish().default(null),
  lspWorkspace: z
    .object({
      rootUri: z.string(),
      documentUri: z.string(),
    })
    .nullish()
    .default(null),
  code: z
    .string()
    .nullish()
    .transform((val) => val ?? getSpCode() ?? ""),
  rawFallback: z.boolean().nullish().default(false),
  gatewayUrl: z.string().nullish().default(""),
  gatewayApiKey: z.string().nullish().default(""),
  version: z
    .string()
    .nullish()
    .transform((val) => val ?? "unknown"),
  mode: z
    .enum(["edit", "read", "home", "run", "gallery"])
    .transform((val): AppMode => {
      if (val === "run") {
        return "read";
      }
      return val;
    }),
  config: passthroughObject,
  configOverrides: passthroughObject,
  appConfig: passthroughObject,
  view: z
    .object({
      showAppCode: z.boolean().default(true),
    })
    .nullish()
    .transform((val) => val ?? { showAppCode: true }),
  serverToken: z
    .string()
    .nullish()
    .transform((val) => val ?? ""),
  session: z.union([
    z.null().optional(),
    z
      .looseObject({
        version: z.literal("1"),
        metadata: z.any(),
        cells: z.array(z.any()),
      })
      .transform((val) => val as api.Session["NotebookSessionV1"]),
  ]),
  notebook: z.union([
    z.null().optional(),
    z
      .looseObject({
        version: z.literal("1"),
        metadata: z.any(),
        cells: z.array(z.any()),
      })
      .transform((val) => val as api.Notebook["NotebookV1"]),
  ]),
  runtimeConfig: z
    .array(
      z.looseObject({
        url: z.string(),
        lazy: z.boolean().default(true),
        authToken: z
          .custom<string | (() => string | Promise<string>)>(
            (v) => v == null || typeof v === "string" || typeof v === "function",
          )
          .nullish(),
      }),
    )
    .nullish()
    .transform((val) => val ?? []),
});

export type ParsedMountOptions = z.infer<typeof mountOptionsSchema>;

export type InitStoreResult = {
  mode: AppMode;
  parsed: ParsedMountOptions;
};

interface InitStoreOptions {
  preloadPage?: (mode: AppMode) => void;
}

/**
 * Applies the branch-variant subset of mount-config atoms.
 */
export function applyMountConfigDeltas(
  parsed: ParsedMountOptions,
  targetStore?: JotaiStore,
): void {
  const s = targetStore ?? store;

  s.set(filenameAtom, parsed.filename);
  s.set(cwdAtom, parsed.cwd ?? null);
  s.set(lspWorkspaceAtom, parsed.lspWorkspace);
  s.set(codeAtom, parsed.code);
  s.set(serverTokenAtom, parsed.serverToken);

  if (parsed.runtimeConfig.length > 0) {
    const firstRuntimeConfig = parsed.runtimeConfig[0];
    Logger.debug("Runtime URL", firstRuntimeConfig.url);
    s.set(runtimeConfigAtom, {
      ...firstRuntimeConfig,
      serverToken: parsed.serverToken,
    });
  } else {
    s.set(runtimeConfigAtom, {
      ...DEFAULT_RUNTIME_CONFIG,
      serverToken: parsed.serverToken,
    });
  }
}

/**
 * Parse mount options and set all non-notebook atoms.
 */
export function initStore(
  options: unknown,
  targetStore?: JotaiStore,
  initOptions: InitStoreOptions = {},
): InitStoreResult {
  const parsedOptions = mountOptionsSchema.safeParse(options);
  if (!parsedOptions.success) {
    Logger.error("Invalid SignalPilot mount options", parsedOptions.error);
    throw new Error("Invalid SignalPilot mount options");
  }

  const mode = parsedOptions.data.mode;
  initOptions.preloadPage?.(mode);

  const s = targetStore ?? store;

  s.set(requestClientAtom, resolveRequestClient());
  initModeRouter();

  s.set(spVersionAtom, parsedOptions.data.version);
  s.set(showCodeInRunModeAtom, parsedOptions.data.view.showAppCode);
  s.set(rawFallbackAtom, parsedOptions.data.rawFallback ?? false);
  s.set(gatewayUrlAtom, parsedOptions.data.gatewayUrl ?? "");
  s.set(gatewayApiKeyAtom, parsedOptions.data.gatewayApiKey ?? "");

  const shouldStartInPresentMode = (() => {
    const url = new URL(window.location.href);
    return url.searchParams.get(KnownQueryParams.viewAs) === "present";
  })();

  const initialViewMode =
    mode === "edit" && shouldStartInPresentMode ? "present" : mode;
  s.set(viewStateAtom, { mode: initialViewMode, cellAnchor: null });

  s.set(
    configOverridesAtom,
    parseConfigOverrides(parsedOptions.data.configOverrides),
  );
  s.set(userConfigAtom, parseUserConfig(parsedOptions.data.config));
  s.set(appConfigAtom, parseAppConfig(parsedOptions.data.appConfig));

  applyMountConfigDeltas(parsedOptions.data, targetStore);

  if (
    parsedOptions.data.runtimeConfig.length > 0 &&
    !parsedOptions.data.runtimeConfig[0].lazy &&
    !isStaticNotebook()
  ) {
    s.set(connectionAtom, { state: WebSocketState.CONNECTING });
  }

  return { mode, parsed: parsedOptions.data };
}
