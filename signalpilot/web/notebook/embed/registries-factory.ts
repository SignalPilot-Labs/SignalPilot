import { UIElementRegistry } from "@/core/dom/uiregistry";
import { RuntimeState } from "@/core/kernel/RuntimeState";
import { VirtualFileTracker } from "@/core/static/virtual-file-tracker";
import { ModelManager } from "@/plugins/impl/anywidget/model";
import { BindingManager } from "@/plugins/impl/anywidget/widget-binding";
import { type ClientRegistries, registerLazyFactory } from "./client-binding";

/**
 * Construct a fresh, isolated set of per-client registries.
 *
 * Factory ordering: UIElementRegistry first, then RuntimeState receives it —
 * RuntimeState's constructor requires a UIElementRegistry instance.
 */
export function createClientRegistries(): ClientRegistries {
  const uiElementRegistry = new UIElementRegistry();
  const runtimeState = new RuntimeState(uiElementRegistry);
  const virtualFileTracker = new VirtualFileTracker();
  const modelManager = new ModelManager();
  const bindingManager = new BindingManager();
  return {
    uiElementRegistry,
    runtimeState,
    virtualFileTracker,
    modelManager,
    bindingManager,
  };
}

// Self-register at module-load time so that any code path that imports
// registries-factory.ts (production: mount.tsx, SpEmbedProviders.tsx;
// tests: setup.ts) automatically provides the factory to client-binding.ts.
// This avoids the require("./registries-factory") relative-path issue in
// Vitest ESM environments.
registerLazyFactory(createClientRegistries);
