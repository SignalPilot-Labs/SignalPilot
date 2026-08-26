import { atom } from "jotai";

export const GATEWAY_PROJECT_STORAGE_KEY = "sp:gateway-project-id";
export const GATEWAY_BRANCH_STORAGE_KEY = "sp:gateway-branch-id";

function readProjectIdFromEnv(): string | null {
  if (typeof window !== "undefined") {
    const fromUrl = new URL(window.location.href).searchParams.get("project");
    if (fromUrl) {
      return fromUrl;
    }
  }
  if (typeof localStorage !== "undefined") {
    return localStorage.getItem(GATEWAY_PROJECT_STORAGE_KEY);
  }
  return null;
}

function readBranchIdFromEnv(): string | null {
  if (typeof localStorage !== "undefined") {
    return localStorage.getItem(GATEWAY_BRANCH_STORAGE_KEY);
  }
  return null;
}

/**
 * Per-client atom: the active gateway project ID.
 *
 * Initial value is read from the URL (?project=) and localStorage when this
 * module is first loaded. Two clients that share the same module-load context
 * start with the same initial value but write independently.
 *
 * Standalone: setGatewayProjectId() persists to localStorage on write.
 * Embed: hosts that want isolation should pre-write
 *   `client.store.set(gatewayProjectIdAtom, value)` before mounting.
 */
export const gatewayProjectIdAtom = atom<string | null>(readProjectIdFromEnv());

/**
 * Per-client atom: the active gateway branch ID.
 *
 * Initial value is read from localStorage when this module is first loaded.
 */
export const gatewayBranchIdAtom = atom<string | null>(readBranchIdFromEnv());
