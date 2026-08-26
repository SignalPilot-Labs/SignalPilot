/**
 * Per-client registry bind stack — mirrors store-binding.ts.
 *
 * Circular import prevention: this file does NOT import from registries-factory.ts
 * or any concrete registry class at module-evaluation time. The module-singleton
 * registries are provided to this file via initModuleRegistries(), called from
 * mount.tsx (standalone) and SpEmbedProviders.tsx (embed) after all modules load.
 *
 * Why not a top-level createClientRegistries() call here: UIElementRegistry and
 * friends import getCurrentRegistries() from this file. If this file eagerly
 * imported registries-factory.ts (which imports those same classes), the circular
 * ES module resolution would try to call `new UIElementRegistry()` before the
 * class is defined — a known ES module circular-init pitfall.
 */

import type { UIElementRegistry } from "@/core/dom/uiregistry";
import type { RuntimeState } from "@/core/kernel/RuntimeState";
import type { VirtualFileTracker } from "@/core/static/virtual-file-tracker";
import type { ModelManager } from "@/plugins/impl/anywidget/model";
import type { BindingManager } from "@/plugins/impl/anywidget/widget-binding";
import type { SignalpilotClient } from "./types";

export interface ClientRegistries {
  readonly uiElementRegistry: UIElementRegistry;
  readonly runtimeState: RuntimeState;
  readonly virtualFileTracker: VirtualFileTracker;
  readonly modelManager: ModelManager;
  readonly bindingManager: BindingManager;
  // PyodideBridge intentionally omitted — stays window-keyed because of
  // Worker + SharedArrayBuffer ownership. See Phase C spec §2.
  // WIDGET_DEF_REGISTRY is intentionally page-global — it deduplicates ESM
  // imports by jsHash and is safe to share across clients.
}

let _moduleRegistriesValue: ClientRegistries | undefined;
let _currentRegistries: ClientRegistries | undefined;
const _bindStack: ClientRegistries[] = [];

// Parallel client stack — push/pop in lockstep with _bindStack.
// Standalone leaves this empty; setDocumentTitle defaults to writing when empty.
const _clientStack: SignalpilotClient[] = [];

/**
 * Optional lazy-factory hook. When set, `_requireModuleRegistries()` calls
 * this instead of falling back to require(). Set by `registerLazyFactory()`
 * which is called from `setup.ts` in test environments and from
 * `registries-factory.ts` at module-load time in production.
 */
let _lazyFactory: (() => ClientRegistries) | undefined;

/**
 * Register a factory function that `_requireModuleRegistries()` can call to
 * auto-initialize when no explicit `initModuleRegistries()` has occurred.
 *
 * This is the safe alternative to `require("./registries-factory")` in
 * ESM/Vitest environments where relative `require()` paths don't resolve
 * correctly from transformed source files.
 *
 * Call this from `registries-factory.ts` (side-effect at module load) and
 * from `setup.ts` in test environments.
 */
export function registerLazyFactory(factory: () => ClientRegistries): void {
  _lazyFactory = factory;
}

/**
 * Called once by mount.tsx (standalone) to provide the module-singleton
 * registries and seed the bind stack. Idempotent — safe to call multiple
 * times (only the first call has effect). After this call, INSTANCE getters
 * on all registry classes are operational.
 */
export function initModuleRegistries(r: ClientRegistries): void {
  if (_moduleRegistriesValue) {
    return; // already initialized — idempotent
  }
  _moduleRegistriesValue = r;
  _bindStack.push(r);
  _currentRegistries = r;
}

/**
 * Ensure module registries are initialized using a factory function, if not
 * already done. The factory is called at most once.
 * Used by SpEmbedProviders when no explicit initModuleRegistries() call has
 * occurred (e.g. embed-only pages that never call mount()).
 * @internal
 */
export function ensureModuleRegistries(
  factory: () => ClientRegistries,
): ClientRegistries {
  if (!_moduleRegistriesValue) {
    initModuleRegistries(factory());
  }
  // _moduleRegistriesValue is guaranteed non-null here (initModuleRegistries
  // always sets it). TypeScript cannot infer this through initModuleRegistries,
  // so we use a runtime-checked cast.
  if (!_moduleRegistriesValue) {
    throw new Error("SignalPilot: ensureModuleRegistries invariant violated");
  }
  return _moduleRegistriesValue;
}

function _requireModuleRegistries(): ClientRegistries {
  if (!_moduleRegistriesValue) {
    if (_lazyFactory) {
      // Factory registered via registerLazyFactory() — preferred path.
      // registries-factory.ts self-registers at module-load time (production:
      // mount.tsx, SpEmbedProviders.tsx; tests: setup.ts or model.test.ts).
      initModuleRegistries(_lazyFactory());
    } else {
      throw new Error(
        "SignalPilot: ClientRegistries not initialized. " +
          "Call initModuleRegistries() (standalone) or ensure registries-factory is " +
          "imported (embed / tests) before accessing INSTANCE getters.",
      );
    }
  }
  if (!_moduleRegistriesValue) {
    throw new Error("SignalPilot: _requireModuleRegistries invariant violated");
  }
  return _moduleRegistriesValue;
}

// Proxy so that consumers of _moduleRegistries always read the live, initialized
// value even if they import it before initModuleRegistries() runs.
export const _moduleRegistries: ClientRegistries = new Proxy(
  {} as ClientRegistries,
  {
    get(_t, p) {
      const r = _requireModuleRegistries();
      return Reflect.get(r, p, r);
    },
  },
);

export function getCurrentRegistries(): ClientRegistries {
  if (_currentRegistries) {
    return _currentRegistries;
  }
  return _requireModuleRegistries();
}

export function bindRegistries(r: ClientRegistries): void {
  _requireModuleRegistries(); // assert initialized
  _bindStack.push(r);
  _currentRegistries = r;
}

export function unbindRegistries(r: ClientRegistries): void {
  if (_bindStack.length === 0) {
    throw new Error("SignalPilot: unbindRegistries called on empty bind stack");
  }
  const top = _bindStack[_bindStack.length - 1];
  if (top !== r) {
    throw new Error(
      "SignalPilot: unbindRegistries called with wrong registries — lifecycle bug",
    );
  }
  _bindStack.pop();
  const prev = _bindStack[_bindStack.length - 1];
  _currentRegistries = prev ?? _requireModuleRegistries();
}

/**
 * Returns the client currently on top of the client stack, or undefined when
 * the stack is empty (standalone mode). Callers use undefined to mean
 * "no embed context bound → apply standalone defaults."
 */
export function getCurrentClient(): SignalpilotClient | undefined {
  return _clientStack[_clientStack.length - 1];
}

/**
 * Push a client onto the stack. Called from SpEmbedProviders in the same
 * synchronous block that calls bindRegistries.
 */
export function bindClient(c: SignalpilotClient): void {
  _clientStack.push(c);
}

/**
 * Pop a client from the stack. Throws on underflow or mismatched pop.
 */
export function unbindClient(c: SignalpilotClient): void {
  if (_clientStack.length === 0) {
    throw new Error("SignalPilot: unbindClient called on empty client stack");
  }
  const top = _clientStack[_clientStack.length - 1];
  if (top !== c) {
    throw new Error(
      "SignalPilot: unbindClient called with wrong client — lifecycle bug",
    );
  }
  _clientStack.pop();
}

/**
 * Reset bind stack to initial state — exposed only for testing.
 * Do NOT call in production code.
 */
export function _resetClientBindStackForTests(): void {
  // In test environments, _moduleRegistriesValue may already be set.
  // Allow re-seeding the stack to the module singleton.
  const mod = _requireModuleRegistries();
  _bindStack.length = 0;
  _bindStack.push(mod);
  _currentRegistries = mod;
  _clientStack.length = 0;
}
