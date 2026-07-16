import {
  applyMountConfigDeltas,
  mountOptionsSchema,
} from "@/core/bootstrap/mount-store";
import { fetchMountConfig, MountConfigError } from "./fetch-mount-config";
import { SPA_NAVIGATE_EVENT } from "@/core/router/spa-navigate";
import { Logger } from "@/utils/Logger";

export { MountConfigError };

interface RebootMountConfigOptions {
  /**
   * The new search params to use for the URL and for fetching mount config.
   * Passed explicitly so ordering vs. history.replaceState is irrelevant.
   */
  searchParams: URLSearchParams;
}

/**
 * Module-level sequence counter for double-click guard.
 *
 * Using a numeric sequence (not a pending promise) so that a fast second
 * call immediately supersedes a slow first call. A pending-promise guard
 * would resolve the second caller with the first call's stale payload.
 */
let currentSeq = 0;

/**
 * Warm reboot of the mount config after a branch switch.
 *
 * Does NOT call `mount()` or `createRoot` — the React tree stays mounted.
 * Only the branch-variant atoms are updated (see `applyMountConfigDeltas`).
 *
 * Steps (ordering is load-bearing):
 * 1. Increment sequence guard.
 * 2. `history.replaceState` — update URL before fetching so the new branch
 *    is reflected in the browser bar immediately.
 * 3. `fetchMountConfig` with explicit search params (decoupled from URL timing).
 * 4. Sequence check — if superseded by a faster second call, bail out silently.
 * 5. Parse and apply mount-config deltas via `applyMountConfigDeltas`.
 * 6. Dispatch `SPA_NAVIGATE_EVENT` so `currentModeAtom` / file-tab subscribers
 *    re-derive.
 * 7. Throws `MountConfigError` on fetch failure. Caller must surface this.
 */
export async function rebootMountConfig(
  opts: RebootMountConfigOptions,
): Promise<void> {
  // 1. Sequence guard — increment and capture.
  const mySeq = ++currentSeq;

  // 2. Update URL immediately so the user sees the new branch in the address bar.
  const newSearch = opts.searchParams.toString();
  window.history.replaceState(null, "", `${window.location.pathname}${newSearch ? `?${newSearch}` : ""}`);

  // 3. Fetch mount config with explicit search params (not relying on window.location).
  const raw = await fetchMountConfig({ search: opts.searchParams });
  // MountConfigError propagates up — no fallback.

  // 4. Sequence check — if a newer call started, discard this result.
  if (mySeq !== currentSeq) {
    Logger.debug(
      `[rebootMountConfig] seq ${mySeq} superseded by ${currentSeq}, discarding`,
    );
    return;
  }

  // 5. Parse and apply branch-variant atoms.
  const parsedResult = mountOptionsSchema.safeParse(raw);
  if (!parsedResult.success) {
    throw new MountConfigError(
      `Mount config parse failed after branch switch: ${parsedResult.error.message}`,
    );
  }

  applyMountConfigDeltas(parsedResult.data);

  // 6. Notify SPA subscribers (currentModeAtom, file-tab effects).
  window.dispatchEvent(
    new CustomEvent(SPA_NAVIGATE_EVENT, {
      detail: { href: window.location.href },
    }),
  );
}
