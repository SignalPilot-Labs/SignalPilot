import { Provider } from "jotai";
import { useEffect, useRef, useState, type PropsWithChildren } from "react";
import {
  bindStore,
  unbindStore,
  getCurrentStore,
} from "@/core/state/store-binding";
import {
  bindRegistries,
  unbindRegistries,
  ensureModuleRegistries,
  bindClient,
  unbindClient,
  type ClientRegistries,
} from "./client-binding";
import { ensureSignalpilotClientRegistries } from "./createSignalpilotClient";
import { EmbedPortalProvider } from "./portal-container";
import { SpEmbedConfigContext } from "./SpEmbedConfigContext";
import { initStoreOnce } from "./initStoreOnce";
import type { SignalpilotClient } from "./types";

type RegistryFactory = () => ClientRegistries;

export interface SpEmbedProvidersProps extends PropsWithChildren {
  client: SignalpilotClient;
  options: unknown;
}

export function SpEmbedProviders({
  client,
  options,
  children,
}: SpEmbedProvidersProps): React.ReactElement {
  const initDone = useRef(false);
  const pluginsRegistered = useRef(false);
  const [registries, setRegistries] = useState<ClientRegistries | null>(null);

  useEffect(() => {
    let cancelled = false;
    initDone.current = false;
    pluginsRegistered.current = false;
    setRegistries(null);
    import("./registries-factory").then((module) => {
      if (!cancelled) {
        const factory: RegistryFactory = module.createClientRegistries;
        ensureModuleRegistries(factory);
        setRegistries(ensureSignalpilotClientRegistries(client, factory));
      }
    });
    return () => {
      cancelled = true;
    };
  }, [client]);

  // Synchronously bind the client store during render so that non-hook code
  // (getRuntimeManager, API headers) can read from it immediately.
  // Re-bind on every render to handle React Strict Mode's unmount/remount
  // (cleanup effect pops the stack; next render must re-push).
  if (registries && getCurrentStore() !== client.store) {
    bindStore(client.store);
    bindRegistries(registries);
    bindClient(client);
  }

  if (registries && !initDone.current) {
    initDone.current = true;
    initStoreOnce(client.store, options);
  }

  // Cleanup: pop the bind stack when unmounting. On Strict Mode remount,
  // the render-phase check above re-pushes before children see stale state.
  useEffect(() => {
    if (!registries) {
      return;
    }
    // Re-bind in effect too, in case the render-phase bind was for a
    // previous render that got discarded (concurrent mode).
    if (getCurrentStore() !== client.store) {
      bindStore(client.store);
      bindRegistries(registries);
      bindClient(client);
    }

    return () => {
      if (getCurrentStore() === client.store) {
        unbindClient(client);
        unbindRegistries(registries);
        unbindStore(client.store);
      }
    };
  }, [client, client.store, registries]);

  useEffect(() => {
    if (!registries || pluginsRegistered.current) {
      return;
    }
    pluginsRegistered.current = true;
    void import("@/plugins/plugins-react").then((module) =>
      module.initializeReactPlugins(),
    );
  }, [registries]);

  if (!registries) {
    return (
      <Provider store={client.store}>
        <EmbedPortalProvider>
          <SpEmbedConfigContext.Provider value={client}>
            <div className="flex h-full flex-1 items-center justify-center text-xs text-muted-foreground">
              loading runtime...
            </div>
          </SpEmbedConfigContext.Provider>
        </EmbedPortalProvider>
      </Provider>
    );
  }

  return (
    <Provider store={client.store}>
      <EmbedPortalProvider>
        <SpEmbedConfigContext.Provider value={client}>
          {children}
        </SpEmbedConfigContext.Provider>
      </EmbedPortalProvider>
    </Provider>
  );
}
