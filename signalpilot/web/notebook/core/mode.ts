import { atom, useAtomValue } from "jotai";
import { KnownQueryParams } from "@/core/constants";
import { SPA_NAVIGATE_EVENT } from "@/core/router/spa-navigate";
import { store } from "./state/jotai";
import type { CellId } from "./cells/ids";

/**
 * This is the internal mode.
 * - `read`: A user is reading the notebook. Cannot switch to edit/present mode.
 * - `edit`: A user is editing the notebook. Can switch to present mode.
 * - `present`: A user is presenting the notebook, it looks like read mode but with some editing features. Cannot switch to present mode.
 * - `home`: A user is in the home page.
 * - `gallery`: A user is in the gallery page.
 */
export type AppMode = "read" | "edit" | "present" | "home" | "gallery";

/**
 * Explicit mode override — set by islands bootstrap, WASM bootstrap, and
 * tests that need a specific mode independent of the URL. When set, this
 * takes precedence over the URL-derived mode. Pass `undefined` to clear.
 */
export const forcedModeAtom = atom<AppMode | undefined>(undefined);

/**
 * Derive the current app mode from `window.location`. Mirrors the server-side
 * URL → mode mapping so the client never disagrees with the server on what
 * mode a URL represents.
 *
 * Returns "home" during SSR (no window) — the embed always overrides via
 * `forcedModeAtom`, so the SSR default is never visible to users.
 */
function readModeFromUrl(): Exclude<AppMode, "present"> {
  if (typeof window === "undefined") return "home";
  const url = new URL(window.location.href);
  if (url.pathname.startsWith("/gallery")) return "gallery";
  if (url.pathname.startsWith("/read")) return "read";
  if (url.searchParams.has(KnownQueryParams.filePath)) return "edit";
  return "home";
}

/**
 * Bumped whenever the URL changes (popstate or spa:navigate). Derived atoms
 * that depend on this will re-evaluate automatically.
 */
const urlRevAtom = atom(0);

/**
 * Reactive app mode atom. Derived from the current URL; overridable via
 * `forcedModeAtom` for islands, WASM, and tests.
 *
 * Re-evaluates on every `popstate` and `spa:navigate` event, causing
 * `SpApp` to swap page components without a document reload.
 */
export const currentModeAtom = atom<Exclude<AppMode, "present">>((get) => {
  get(urlRevAtom); // subscribe to URL changes
  const forced = get(forcedModeAtom);
  if (forced !== undefined && forced !== "present") return forced;
  return readModeFromUrl();
});

/**
 * Wire URL changes to `urlRevAtom` so `currentModeAtom` re-derives.
 * Call once at app boot (from mount.tsx and islands bootstrap).
 * Idempotent — safe to call multiple times; each call adds one listener pair
 * but listeners are identical and the bump is idempotent in effect.
 *
 * Keeping this out of module-load side effects avoids load-order coupling
 * in tests that import mode.ts before stubbing window.
 */
let modeRouterInitialized = false;
export function initModeRouter(): void {
  if (typeof window === "undefined") return;
  if (modeRouterInitialized) return;
  modeRouterInitialized = true;
  const bump = () => store.set(urlRevAtom, (n) => n + 1);
  window.addEventListener("popstate", bump);
  window.addEventListener(SPA_NAVIGATE_EVENT, bump);
}

/**
 * Read the current app mode synchronously. Reads `currentModeAtom` from the
 * store (which is URL-derived + optional forced override).
 */
export function getCurrentAppMode(): Exclude<AppMode, "present"> {
  return store.get(currentModeAtom);
}

export function toggleAppMode(mode: AppMode): AppMode {
  // Can't switch to present mode.
  if (mode === "read" || mode === "home" || mode === "gallery") {
    return mode;
  }

  return mode === "edit" ? "present" : "edit";
}

/**
 * View state for the app.
 */
interface ViewState {
  /**
   * The mode of the app: read/edit/present
   */
  mode: AppMode;
  /**
   * A cell ID to anchor scrolling to when toggling between presenting and
   * editing views
   */
  cellAnchor: CellId | null;
}

export async function runDuringPresentMode(
  fn: () => void | Promise<void>,
): Promise<void> {
  const state = store.get(viewStateAtom);
  if (state.mode === "present") {
    await fn();
    return;
  }

  store.set(viewStateAtom, { ...state, mode: "present" });
  // Wait 100ms to allow the page to render
  await new Promise((resolve) => setTimeout(resolve, 100));
  // Wait 2 frames
  await new Promise((resolve) => requestAnimationFrame(resolve));
  await new Promise((resolve) => requestAnimationFrame(resolve));
  await fn();
  store.set(viewStateAtom, { ...state, mode: "edit" });
  return undefined;
}

export const viewStateAtom = atom<ViewState>({
  mode: "not-set" as AppMode,
  cellAnchor: null,
});

export const kioskModeAtom = atom<boolean>(false);

/**
 * Whether installing packages is allowed in the current view. False in read
 * mode, since end-users of a deployed notebook cannot mutate its environment.
 */
export function useInstallAllowed(): boolean {
  const { mode } = useAtomValue(viewStateAtom);
  return mode !== "read";
}
