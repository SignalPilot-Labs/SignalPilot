import { atom } from "jotai";
import { Logger } from "@/utils/Logger";
import { connectionAtom } from "../network/connection";
import { store } from "../state/jotai";
import { WebSocketState } from "../websocket/types";

/**
 * Kernel launch state machine — the single source of truth for every surface
 * that reflects a kernel coming up (run buttons, the kernel status island,
 * the footer chip).
 *
 * Lazy runtimes provision on demand, so "the kernel is starting" is a
 * first-class product moment rather than an error condition. All launch
 * entrypoints (first Run, manual connect, background prewarm) funnel through
 * `launchRuntime` so the UI can never disagree with what the runtime is
 * actually doing.
 */

export type KernelLaunchPhase =
  | "idle"
  | "provisioning" // creating the session + booting the cloud sandbox
  | "connecting" // opening the notebook <-> kernel socket
  | "starting" // waiting for the Python kernel to come up
  | "ready" // fully up (transient — auto-clears back to idle)
  | "error";

export type KernelLaunchTrigger = "run" | "manual" | "prewarm";

export interface KernelLaunchState {
  phase: KernelLaunchPhase;
  trigger: KernelLaunchTrigger | null;
  /** Epoch ms when the current launch attempt began. */
  startedAt: number | null;
  error: string | null;
}

const IDLE: KernelLaunchState = {
  phase: "idle",
  trigger: null,
  startedAt: null,
  error: null,
};

export const kernelLaunchAtom = atom<KernelLaunchState>(IDLE);

/** True while a launch is actively in flight (not idle/ready/error). */
export function isKernelLaunchInFlight(state: KernelLaunchState): boolean {
  return (
    state.phase === "provisioning" ||
    state.phase === "connecting" ||
    state.phase === "starting"
  );
}

const READY_LINGER_MS = 2500;
let readyTimer: ReturnType<typeof setTimeout> | undefined;

function setPhase(phase: KernelLaunchPhase, patch?: Partial<KernelLaunchState>) {
  store.set(kernelLaunchAtom, {
    ...store.get(kernelLaunchAtom),
    phase,
    ...patch,
  });
}

/**
 * A Run issued while a background prewarm is mid-flight adopts the launch:
 * the copy shifts from "preparing in the background" to "starting your run"
 * without restarting the state machine.
 */
export function adoptKernelLaunch(trigger: KernelLaunchTrigger): void {
  const current = store.get(kernelLaunchAtom);
  if (isKernelLaunchInFlight(current) && current.trigger === "prewarm") {
    setPhase(current.phase, { trigger });
  }
}

export function dismissKernelLaunchError(): void {
  if (store.get(kernelLaunchAtom).phase === "error") {
    store.set(kernelLaunchAtom, IDLE);
  }
}

/**
 * Bring the runtime all the way up — provision (lazy), WebSocket open,
 * kernel instantiated — driving `kernelLaunchAtom` through each stage.
 * Safe to call when already connected (no-ops the UI state). Concurrent
 * callers share the same underlying work: RuntimeManager.init() and the
 * wait helpers are idempotent.
 */
export async function launchRuntime(trigger: KernelLaunchTrigger): Promise<void> {
  const [
    { getRuntimeManager },
    { waitForConnectionOpen },
    { waitForKernelToBeInstantiated },
  ] = await Promise.all([
    import("./config"),
    import("../network/connection"),
    import("../kernel/state"),
  ]);
  const runtimeManager = getRuntimeManager();

  // Already fully connected: nothing to show, just make sure the kernel
  // waits are settled for the caller.
  if (store.get(connectionAtom).state === WebSocketState.OPEN) {
    await waitForKernelToBeInstantiated();
    return;
  }

  const current = store.get(kernelLaunchAtom);
  if (isKernelLaunchInFlight(current)) {
    // A launch is already running (e.g. prewarm). Adopt it rather than
    // resetting the visible progress.
    if (trigger !== "prewarm") {
      adoptKernelLaunch(trigger);
    }
  } else {
    if (readyTimer !== undefined) {
      clearTimeout(readyTimer);
      readyTimer = undefined;
    }
    store.set(kernelLaunchAtom, {
      phase: "provisioning",
      trigger,
      startedAt: Date.now(),
      error: null,
    });
  }

  if (store.get(connectionAtom).state === WebSocketState.NOT_STARTED) {
    store.set(connectionAtom, { state: WebSocketState.CONNECTING });
  }

  try {
    await runtimeManager.init();
    if (isKernelLaunchInFlight(store.get(kernelLaunchAtom))) {
      setPhase("connecting");
    }
    await waitForConnectionOpen();
    if (isKernelLaunchInFlight(store.get(kernelLaunchAtom))) {
      setPhase("starting");
    }
    await waitForKernelToBeInstantiated();
    if (isKernelLaunchInFlight(store.get(kernelLaunchAtom))) {
      setPhase("ready");
      readyTimer = setTimeout(() => {
        readyTimer = undefined;
        if (store.get(kernelLaunchAtom).phase === "ready") {
          store.set(kernelLaunchAtom, IDLE);
        }
      }, READY_LINGER_MS);
    }
  } catch (error) {
    Logger.error("Kernel launch failed", error);
    if (store.get(connectionAtom).state === WebSocketState.CONNECTING) {
      store.set(connectionAtom, { state: WebSocketState.NOT_STARTED });
    }
    const launch = store.get(kernelLaunchAtom);
    if (launch.trigger === "prewarm") {
      // Background prewarms fail silently — the eventual Run retries and
      // is the right moment to surface a problem.
      store.set(kernelLaunchAtom, IDLE);
    } else {
      setPhase("error", {
        error: error instanceof Error ? error.message : String(error),
      });
    }
    throw error;
  }
}
