import { createStore } from "jotai";
import { generateUUID } from "@/utils/uuid";
import type { ClientRegistries } from "./client-binding";
import type { SignalpilotClient, SignalpilotClientOptions } from "./types";

const CLIENT_REGISTRIES = Symbol("SignalpilotClient.registries");

type MutableSignalpilotClient = SignalpilotClient & {
  [CLIENT_REGISTRIES]?: ClientRegistries;
};

export function createSignalpilotClient(
  options?: SignalpilotClientOptions,
): SignalpilotClient {
  const instanceId = options?.instanceId ?? generateUUID();
  const frozenOptions: Readonly<SignalpilotClientOptions> = Object.freeze({
    writeDocumentTitle: false,
    ...options,
    instanceId,
  });

  const client: MutableSignalpilotClient = {
    instanceId,
    options: frozenOptions,
    store: createStore(),
    get registries() {
      const registries = this[CLIENT_REGISTRIES];
      if (!registries) {
        throw new Error("SignalPilot client registries are not initialized");
      }
      return registries;
    },
    dispose(): void {
      this[CLIENT_REGISTRIES]?.runtimeState.stop();
      // UIElementRegistry / VirtualFileTracker / ModelManager have no native
      // teardown; their refs drop when the client object is GC'd.
    },
  };
  return client;
}

export function ensureSignalpilotClientRegistries(
  client: SignalpilotClient,
  factory: () => ClientRegistries,
): ClientRegistries {
  const mutableClient = client as MutableSignalpilotClient;
  mutableClient[CLIENT_REGISTRIES] ??= factory();
  return mutableClient[CLIENT_REGISTRIES];
}
