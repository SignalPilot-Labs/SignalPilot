import type * as api from "@/packages/sp-api";
import { Provider } from "jotai";
import { createRoot } from "react-dom/client";
import { z } from "zod";
import {
  appConfigAtom,
  configOverridesAtom,
  userConfigAtom,
} from "@/core/config/config";
import { KnownQueryParams } from "@/core/constants";
import { getSpCode } from "@/core/meta/globals";
import {
  spVersionAtom,
  serverTokenAtom,
  showCodeInRunModeAtom,
  rawFallbackAtom,
  gatewayUrlAtom,
  gatewayApiKeyAtom,
} from "@/core/meta/state";
import { Logger } from "@/utils/Logger";
import { ErrorBoundary } from "./components/editor/boundary/ErrorBoundary";
import {
  parseAppConfig,
  parseConfigOverrides,
  parseUserConfig,
} from "./core/config/config-schema";
import { SpApp, preloadPage } from "./core/SpApp";
import { type AppMode, initModeRouter, viewStateAtom } from "./core/mode";
import { cleanupAuthQueryParams } from "./core/network/auth";
import { connectionAtom } from "./core/network/connection";
import { requestClientAtom } from "./core/network/requests";
import { resolveRequestClient } from "./core/network/resolve";
import {
  DEFAULT_RUNTIME_CONFIG,
  runtimeConfigAtom,
} from "./core/runtime/config";
import {
  codeAtom,
  cwdAtom,
  filenameAtom,
  lspWorkspaceAtom,
} from "./core/saving/file-state";
import { store, type JotaiStore } from "./core/state/jotai";
import { _moduleSingleton, bindStore } from "./core/state/store-binding";
import { initModuleRegistries } from "./embed/client-binding";
import { createClientRegistries } from "./embed/registries-factory";
import { patchFetch, patchVegaLoader } from "./core/static/files";

import {
  getStaticModelNotifications,
  isStaticNotebook,
} from "./core/static/static-state";
import { maybeRegisterVSCodeBindings } from "./core/vscode/vscode-bindings";

import { WebSocketState } from "./core/websocket/types";
import {
  handleWidgetMessage,
  MODEL_MANAGER,
} from "./plugins/impl/anywidget/model";
import { vegaLoader } from "./plugins/impl/vega/loader";
import { initializeCustomElements } from "./plugins/plugins";

let hasMounted = false;

/**
 * The parsed mount options plus the resolved mode.
 * Returned by initStore() so initEditState() doesn't re-parse.
 */
type InitStoreResult = {
  mode: AppMode;
  parsed: z.infer<typeof mountOptionsSchema>;
};

/**
 * Main entry point for the sp app.
 *
 * Sets up the sp app with a theme provider.
 * Returns a Promise that resolves when rendering is underway, or rejects on
 * initEditState() failure (propagated to main.tsx → renderBootError).
 */
export async function mount(
  options: unknown,
  el: Element,
): Promise<void> {
  if (hasMounted) {
    Logger.warn("SignalPilot app has already been mounted.");
    return;
  }

  hasMounted = true;

  // Standalone: #root becomes the .sp-root container so rescoped CSS selectors
  // (body → .sp-root, :root → .sp-root) match without poisoning the host page.
  (el as HTMLElement).classList.add("sp-root", "dark", "dark-theme");
  (el as HTMLElement).dataset.theme = "dark";

  let initResult: InitStoreResult;

  try {
    // Init side-effects
    maybeRegisterVSCodeBindings();
    initializeCustomElements();
    cleanupAuthQueryParams();

    // Patches
    if (isStaticNotebook()) {
      // If we're in static mode, we need to patch fetch to use the virtual file
      patchFetch();
      patchVegaLoader(vegaLoader);
      hydrateStaticModels();
    }

    // Initialize module-singleton registries. createClientRegistries() is called
    // here (not at import time) to avoid the circular ES module init issue:
    // class modules import client-binding.ts, which would create a load-order
    // cycle if registries-factory.ts were imported at the top of client-binding.ts.
    initModuleRegistries(createClientRegistries());
    // Bind module singleton so proxy routes to the right store and registries.
    // initModuleRegistries already seeded the registry bind stack; no bindRegistries
    // call needed for the standalone path.
    bindStore(_moduleSingleton);
    // Init store — sync parse, all atom sets, networking
    initResult = initStore(options);
  } catch (error) {
    // Most likely, configuration failed to parse.
    const root = createRoot(el);
    const Throw = () => {
      throw error;
    };
    root.render(
      <ErrorBoundary>
        <Throw />
      </ErrorBoundary>,
    );
    return;
  }

  const { mode, parsed } = initResult;

  // Lazily load plugin classes so they don't appear in the home critical path.
  // edit-page is itself lazy (separate chunk); plugin registration is
  // idempotent (registerReactComponent). UI elements are encountered as the
  // kernel streams cells in, so this dynamic import races safely.
  if (mode === "edit" || mode === "read") {
    // Await cells/session/store init so a failure surfaces to renderBootError
    // before createRoot. Plugin registry loads in parallel — registration is
    // idempotent and cells stream in after the kernel handshake.
    await initEditState(parsed, mode);
    void import("./plugins/plugins-react").then((m) =>
      m.initializeReactPlugins(),
    );
  }

  const root = createRoot(el);
  root.render(
    <Provider store={_moduleSingleton}>
      <SpApp />
    </Provider>,
  );
}

/**
 * Dynamically imports cells/session/wasm-store and performs notebook hydration.
 * Kept separate so these heavy modules are excluded from the home entry chunk.
 * Rejections propagate to mount() → main.tsx catch → renderBootError (fail-fast).
 */
async function initEditState(
  parsed: z.infer<typeof mountOptionsSchema>,
  mode: AppMode,
): Promise<void> {
  const [cellsModule, sessionModule] = await Promise.all([
    import("./core/cells/cells"),
    import("./core/cells/session"),
  ]);

  const { notebookAtom } = cellsModule;
  const { notebookStateFromSession } = sessionModule;

  // Session/notebook hydration
  const notebook = notebookStateFromSession(parsed.session, parsed.notebook);
  if (notebook) {
    store.set(notebookAtom, notebook);
  }

}

const passthroughObject = z
  .looseObject({})
  .nullish()
  .default({}) // Default to empty object
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

// This should be extremely backwards compatible and require no options
export const mountOptionsSchema = z.object({
  /**
   * filename of the notebook to open
   */
  filename: z
    .string()
    .nullish()
    .transform((val) => val ?? null),
  /**
   * absolute working directory of the notebook
   */
  cwd: z.string().nullish().default(null),
  /**
   * LSP workspace information
   */
  lspWorkspace: z
    .object({
      rootUri: z.string(),
      documentUri: z.string(),
    })
    .nullish()
    .default(null),
  /**
   * notebook code
   */
  code: z
    .string()
    .nullish()
    .transform((val) => val ?? getSpCode() ?? ""),
  /**
   * True when the backend opened a non-notebook file in raw-editor fallback mode.
   */
  rawFallback: z.boolean().nullish().default(false),
  /**
   * Base URL for the SignalPilot data gateway API.
   */
  gatewayUrl: z.string().nullish().default(""),
  /**
   * API key for the SignalPilot gateway.
   */
  gatewayApiKey: z.string().nullish().default(""),
  /**
   * sp version
   */
  version: z
    .string()
    .nullish()
    .transform((val) => val ?? "unknown"),
  /**
   * 'edit' or 'read'/'run' or 'home' or 'gallery'
   */
  mode: z
    .enum(["edit", "read", "home", "run", "gallery"])
    .transform((val): AppMode => {
      if (val === "run") {
        return "read";
      }
      return val;
    }),
  /**
   * sp config
   */
  config: passthroughObject,
  /**
   * sp config overrides
   */
  configOverrides: passthroughObject,
  /**
   * sp app config
   */
  appConfig: passthroughObject,
  /**
   * show code in run mode
   */
  view: z
    .object({
      showAppCode: z.boolean().default(true),
    })
    .nullish()
    .transform((val) => val ?? { showAppCode: true }),

  /**
   * server token
   */
  serverToken: z
    .string()
    .nullish()
    .transform((val) => val ?? ""),

  /**
   * Serialized Session["NotebookSessionV1"] snapshot
   */
  session: z.union([
    z.null().optional(),
    z
      .looseObject({
        // Rough shape, we don't need to validate the full schema
        version: z.literal("1"),
        metadata: z.any(),
        cells: z.array(z.any()),
      })
      .transform((val) => val as api.Session["NotebookSessionV1"]),
  ]),

  /**
   * Serialized Notebook["NotebookV1"] snapshot
   */
  notebook: z.union([
    z.null().optional(),
    z
      .looseObject({
        // Rough shape, we don't need to validate the full schema
        version: z.literal("1"),
        metadata: z.any(),
        cells: z.array(z.any()),
      })
      .transform((val) => val as api.Notebook["NotebookV1"]),
  ]),

  /**
   * Runtime configs
   */
  runtimeConfig: z
    .array(
      z.looseObject({
        url: z.string(),
        // Lazy by default, but can be overridden by the runtime config
        lazy: z.boolean().default(true),
        authToken: z.string().nullish(),
      }),
    )
    .nullish()
    .transform((val) => val ?? []),
});

/**
 * The parsed mount options type. Used by `applyMountConfigDeltas` and
 * `reboot-mount.ts` so they share the same schema-derived type.
 */
export type ParsedMountOptions = z.infer<typeof mountOptionsSchema>;

/**
 * Applies the branch-variant subset of mount-config atoms.
 *
 * Called by both `initStore()` (cold boot) and `rebootMountConfig()` (warm
 * reboot on branch switch). Keeping one source of truth avoids drift between
 * the two paths.
 *
 * Atoms written (branch-variant or session-variant):
 *   - filenameAtom       — branch may have a different active file
 *   - cwdAtom            — branch may change working directory
 *   - lspWorkspaceAtom   — branch-scoped LSP workspace
 *   - codeAtom           — file content differs per branch
 *   - serverTokenAtom    — backend may rotate the token
 *   - runtimeConfigAtom  — backend may regenerate session token / lazy flag
 *
 * Atoms deliberately SKIPPED (with one-line justification):
 *   - requestClientAtom      — networking layer, branch-invariant
 *   - spVersionAtom          — server version, doesn't change mid-session
 *   - showCodeInRunModeAtom  — view setting from initial URL only
 *   - rawFallbackAtom        — boot-time only
 *   - gatewayUrlAtom         — gateway is branch-invariant
 *   - gatewayApiKeyAtom      — gateway is branch-invariant
 *   - viewStateAtom          — preserve current view on branch switch
 *   - configOverridesAtom    — global config, not per-branch
 *   - userConfigAtom         — global config, not per-branch
 *   - appConfigAtom          — global config, not per-branch
 *   - connectionAtom         — managed by WS layer; reconnect effect handles state
 *   - initModeRouter()       — already wired on cold boot; re-init would double-register popstate
 *   - preloadPage(mode)      — boot-only
 */
export function applyMountConfigDeltas(
  parsed: ParsedMountOptions,
  targetStore?: JotaiStore,
): void {
  // When an explicit targetStore is provided (embed path), write directly to it
  // instead of going through the proxy. This avoids a class of bugs where the
  // proxy's getCurrentStore() returns the wrong store due to bind-stack timing.
  const s = targetStore ?? store;

  // Files (branch-variant)
  s.set(filenameAtom, parsed.filename);
  s.set(cwdAtom, parsed.cwd ?? null);
  s.set(lspWorkspaceAtom, parsed.lspWorkspace);
  s.set(codeAtom, parsed.code);

  // Server token (may rotate on reboot)
  s.set(serverTokenAtom, parsed.serverToken);

  // Runtime config (may regenerate session token / lazy flag)
  if (parsed.runtimeConfig.length > 0) {
    const firstRuntimeConfig = parsed.runtimeConfig[0];
    Logger.debug("⚡ Runtime URL", firstRuntimeConfig.url);
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
 * Parse mount options and set all non-notebook atoms. Returns the parsed mode
 * and the full parsed data so callers don't re-parse.
 *
 * @param targetStore - When provided (embed path), all atom writes go directly
 *   to this store instead of through the proxy. This eliminates the class of
 *   bugs where getCurrentStore() might return the wrong store.
 */
export function initStore(
  options: unknown,
  targetStore?: JotaiStore,
): InitStoreResult {
  const parsedOptions = mountOptionsSchema.safeParse(options);
  if (!parsedOptions.success) {
    Logger.error("Invalid SignalPilot mount options", parsedOptions.error);
    throw new Error("Invalid SignalPilot mount options");
  }
  const mode = parsedOptions.data.mode;
  preloadPage(mode);

  // Use the explicit target store if provided; otherwise fall back to the proxy.
  const s = targetStore ?? store;

  // Configure networking layer (boot-only, branch-invariant)
  s.set(requestClientAtom, resolveRequestClient());

  // currentModeAtom is now URL-derived; initModeRouter() wires popstate/spa:navigate.
  // Boot-only — do NOT re-call on warm reboot (would double-register popstate).
  initModeRouter();

  // Meta (boot-only, branch-invariant)
  s.set(spVersionAtom, parsedOptions.data.version);
  s.set(showCodeInRunModeAtom, parsedOptions.data.view.showAppCode);
  s.set(rawFallbackAtom, parsedOptions.data.rawFallback ?? false);
  s.set(gatewayUrlAtom, parsedOptions.data.gatewayUrl ?? "");
  s.set(gatewayApiKeyAtom, parsedOptions.data.gatewayApiKey ?? "");

  // Check for view-as parameter to start in present mode (boot-only)
  const shouldStartInPresentMode = (() => {
    const url = new URL(window.location.href);
    return url.searchParams.get(KnownQueryParams.viewAs) === "present";
  })();

  const initialViewMode =
    mode === "edit" && shouldStartInPresentMode ? "present" : mode;
  s.set(viewStateAtom, { mode: initialViewMode, cellAnchor: null });

  // Config (global, not per-branch)
  s.set(
    configOverridesAtom,
    parseConfigOverrides(parsedOptions.data.configOverrides),
  );
  s.set(userConfigAtom, parseUserConfig(parsedOptions.data.config));
  s.set(appConfigAtom, parseAppConfig(parsedOptions.data.appConfig));

  // Branch-variant atoms (shared with warm reboot path)
  applyMountConfigDeltas(parsedOptions.data, targetStore);

  // connectionAtom: only on cold boot, when the runtime is eager
  // (warm reboot triggers reconnect via gatewayBranchIdAtom effect in edit-app.tsx)
  if (
    parsedOptions.data.runtimeConfig.length > 0 &&
    !parsedOptions.data.runtimeConfig[0].lazy &&
    !isStaticNotebook()
  ) {
    s.set(connectionAtom, { state: WebSocketState.CONNECTING });
  }

  return { mode, parsed: parsedOptions.data };
}

/**
 * Hydrate anywidget models from embedded static state so widgets
 * render immediately without a kernel connection.
 */
function hydrateStaticModels(): void {
  const notifications = getStaticModelNotifications();
  if (!notifications) {
    return;
  }
  for (const notification of notifications) {
    handleWidgetMessage(MODEL_MANAGER, notification);
  }
}

export const visibleForTesting = {
  reset: () => {
    hasMounted = false;
  },
};
