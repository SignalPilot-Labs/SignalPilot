import { atom, useAtom, useAtomValue } from "jotai";
import useEvent from "react-use-event-hook";
import { Logger } from "@/utils/Logger";
import { connectionAtom } from "../network/connection";
import { store } from "../state/jotai";
import { isAppNotStarted } from "../websocket/connection-utils";
import { WebSocketState } from "../websocket/types";
import { RuntimeManager } from "./runtime";
import type { RuntimeConfig } from "./types";

function getBaseURI(): string {
  // Guard for SSR / environments without DOM
  if (typeof document === "undefined") return "/";
  const url = new URL(document.baseURI);
  url.search = "";
  url.hash = "";
  return url.toString();
}

export const DEFAULT_RUNTIME_CONFIG: RuntimeConfig = {
  lazy: true,
  url: getBaseURI(),
};

export const runtimeConfigAtom = atom<RuntimeConfig>(DEFAULT_RUNTIME_CONFIG);
const runtimeManagerAtom = atom<RuntimeManager>((get) => {
  const config = get(runtimeConfigAtom);
  return new RuntimeManager(config, config.lazy);
});

export function useRuntimeManager(): RuntimeManager {
  return useAtomValue(runtimeManagerAtom);
}

export function useConnectToRuntime(): () => Promise<void> {
  const runtimeManager = useRuntimeManager();
  const [connection, setConnection] = useAtom(connectionAtom);
  return useEvent(async () => {
    if (isAppNotStarted(connection.state)) {
      setConnection({ state: WebSocketState.CONNECTING });
      try {
        await runtimeManager.init();
      } catch (error) {
        // Lazy provisioning failed (e.g. session create error) — return to
        // NOT_STARTED so the connect affordances remain clickable.
        setConnection({ state: WebSocketState.NOT_STARTED });
        throw error;
      }
    } else {
      Logger.log("Runtime already started or starting...");
    }
  });
}

/**
 * Prefer to use useRuntimeManager instead of this function.
 */
export function getRuntimeManager(): RuntimeManager {
  return store.get(runtimeManagerAtom);
}

/**
 * Bring the runtime all the way up — provision (lazy), health, WebSocket
 * open, kernel instantiated — and only then return. Safe to call when
 * already connected. Used by run flows that must reconcile against
 * kernel-ready state (fresh kernels re-id every cell) before building
 * their request payloads.
 */
export async function connectToRuntimeAndWaitReady(): Promise<void> {
  const [{ waitForConnectionOpen }, { waitForKernelToBeInstantiated }] =
    await Promise.all([
      import("../network/connection"),
      import("../kernel/state"),
    ]);
  const runtimeManager = getRuntimeManager();
  if (isAppNotStarted(store.get(connectionAtom).state)) {
    store.set(connectionAtom, { state: WebSocketState.CONNECTING });
  }
  try {
    await runtimeManager.init();
  } catch (error) {
    if (store.get(connectionAtom).state === WebSocketState.CONNECTING) {
      store.set(connectionAtom, { state: WebSocketState.NOT_STARTED });
    }
    throw error;
  }
  await waitForConnectionOpen();
  await waitForKernelToBeInstantiated();
}

export function asRemoteURL(path: string): URL {
  if (path.startsWith("http")) {
    return new URL(path);
  }
  let base = getRuntimeManager().httpURL.toString();
  if (base.startsWith("blob:")) {
    // Remove leading blob:
    base = base.replace("blob:", "");
  }
  return new URL(path, base);
}
