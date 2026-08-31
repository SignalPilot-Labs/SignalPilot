import { Logger } from "@/utils/Logger";

/**
 * Hooks that must run before a lazy runtime is provisioned (i.e. before the
 * sandbox session is created on first Run). The canonical use is flushing
 * unsaved local edits to the workspace store so the fresh kernel hydrates
 * the code the user is actually looking at.
 *
 * Kept as a tiny standalone registry to avoid an import cycle between the
 * runtime layer and the saving layer.
 */

type PreProvisionHook = () => Promise<void> | void;

const hooks = new Set<PreProvisionHook>();

export function registerPreProvisionHook(hook: PreProvisionHook): () => void {
  hooks.add(hook);
  return () => hooks.delete(hook);
}

/** Run all hooks; failures are logged but never block provisioning. */
export async function runPreProvisionHooks(): Promise<void> {
  for (const hook of hooks) {
    try {
      await hook();
    } catch (error) {
      Logger.error("Pre-provision hook failed (continuing)", error);
    }
  }
}
