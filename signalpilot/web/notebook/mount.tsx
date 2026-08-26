import { Provider } from "jotai";
import { createRoot } from "react-dom/client";
import { Logger } from "@/utils/Logger";
import { ErrorBoundary } from "./components/editor/boundary/ErrorBoundary";
import {
  initStore,
  type InitStoreResult,
  type ParsedMountOptions,
} from "./core/bootstrap/mount-store";
import { SpApp, preloadPage } from "./core/SpApp";
import type { AppMode } from "./core/mode";
import { cleanupAuthQueryParams } from "./core/network/auth";
import { store } from "./core/state/jotai";
import { _moduleSingleton, bindStore } from "./core/state/store-binding";
import { initModuleRegistries } from "./embed/client-binding";
import { createClientRegistries } from "./embed/registries-factory";
import { patchFetch, patchVegaLoader } from "./core/static/files";

import {
  getStaticModelNotifications,
  isStaticNotebook,
} from "./core/static/static-state";
import { maybeRegisterVSCodeBindings } from "./core/vscode/vscode-bindings";

import {
  handleWidgetMessage,
  MODEL_MANAGER,
} from "./plugins/impl/anywidget/model";
import { vegaLoader } from "./plugins/impl/vega/loader";
import { initializeCustomElements } from "./plugins/plugins";

let hasMounted = false;

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
  (el as HTMLElement).classList.add("sp-root");

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
    initResult = initStore(options, undefined, { preloadPage });
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
  parsed: ParsedMountOptions,
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
