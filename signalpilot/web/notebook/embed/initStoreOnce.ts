import { initStore } from "@/core/bootstrap/mount-store";
import type { JotaiStore } from "@/core/state/jotai";

const _initialized = new WeakSet<JotaiStore>();

/**
 * Calls `initStore(options, store)` at most once per `store` instance.
 *
 * The explicit `store` parameter is passed through to `initStore` so that all
 * atom writes target the per-client store directly — bypassing the global
 * proxy store whose `getCurrentStore()` is fragile under concurrent renders
 * and bind-stack timing.
 *
 * Throws unconditionally on a second call for the same store (fail-fast;
 * both dev and prod). Inside a React tree, propagatable via an error boundary.
 */
export function initStoreOnce(store: JotaiStore, options: unknown): void {
  if (_initialized.has(store)) {
    throw new Error(
      "SignalPilot: initStoreOnce called more than once for the same store. " +
        "Each SignalpilotClient must be mounted at most once at a time.",
    );
  }
  _initialized.add(store);
  initStore(options, store);
}
