import { createStore } from "jotai";
import { generateUUID } from "@/utils/uuid";
import { createClientRegistries } from "./registries-factory";
import type { SignalpilotClient, SignalpilotClientOptions } from "./types";

export function createSignalpilotClient(
  options?: SignalpilotClientOptions,
): SignalpilotClient {
  const instanceId = options?.instanceId ?? generateUUID();
  const frozenOptions: Readonly<SignalpilotClientOptions> = Object.freeze({
    writeDocumentTitle: false,
    ...options,
    instanceId,
  });

  const registries = createClientRegistries();

  return {
    instanceId,
    options: frozenOptions,
    store: createStore(),
    registries,
    dispose(): void {
      registries.runtimeState.stop();
      // UIElementRegistry / VirtualFileTracker / ModelManager have no native
      // teardown; their refs drop when the client object is GC'd.
    },
  };
}
