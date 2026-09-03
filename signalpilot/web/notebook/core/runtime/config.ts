import { atom, useAtom, useAtomValue } from "jotai";
import useEvent from "react-use-event-hook";
import { Logger } from "@/utils/Logger";
import { connectionAtom } from "../network/connection";
import { store } from "../state/jotai";
import { isAppNotStarted } from "../websocket/connection-utils";
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
  const [connection] = useAtom(connectionAtom);
  return useEvent(async () => {
    if (isAppNotStarted(connection.state)) {
      // Drive the shared launch state machine so every surface (run
      // buttons, kernel island, footer chip) reflects this connect.
      const { launchRuntime } = await import("./launch-state");
      await launchRuntime("manual");
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
  const { launchRuntime } = await import("./launch-state");
  await launchRuntime("run");
}

export function asRemoteURL(path: string): URL {
  if (path.startsWith("http")) {
    return new URL(path);
  }
  let base = getRuntimeManager().httpBaseURL.toString();
  if (base.startsWith("blob:")) {
    // Remove leading blob:
    base = base.replace("blob:", "");
  }
  return new URL(path, base);
}
