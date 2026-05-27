/**
 * Per-client registry bind stack — mirrors store-binding.ts.
 *
 * Both entry points (mount.tsx for standalone, SpEmbedProviders.tsx for embed)
 * explicitly call into this file. No lazy/fallback init exists.
 *
 * Circular import prevention: this file does NOT import from registries-factory.ts
 * or any concrete registry class at module-evaluation time. The module-singleton
 * registries are provided to this file via initModuleRegistries(), called from
 * mount.tsx (standalone) after all modules load.
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

function _requireModuleRegistries(): ClientRegistries {
  if (!_moduleRegistriesValue) {
    throw new Error(
      "SignalPilot: ClientRegistries not initialized. " +
        "Call initModuleRegistries() (standalone) or bindRegistries() (embed) " +
        "before accessing INSTANCE getters.",
    );
  }
  return _moduleRegistriesValue;
}

export function getCurrentRegistries(): ClientRegistries {
  if (_currentRegistries) {
    return _currentRegistries;
  }
  return _requireModuleRegistries();
}

export function bindRegistries(r: ClientRegistries): void {
  // No module-singleton assertion: embed mode calls bindRegistries without a
  // preceding initModuleRegistries(). The per-client registries pushed here
  // ARE the live registries; _currentRegistries is sufficient.
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
  // In standalone mode the module singleton is always in the stack; `prev` is
  // guaranteed to be set after popping the per-client entry. In embed-only mode
  // the stack may empty on the last client's unmount — fall back to the module
  // singleton when available, otherwise clear _currentRegistries.
  _currentRegistries = prev ?? _moduleRegistriesValue;
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
