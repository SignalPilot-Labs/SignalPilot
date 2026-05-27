import { Provider } from "jotai";
import { useEffect, useRef, type PropsWithChildren } from "react";
import {
  bindStore,
  unbindStore,
  getCurrentStore,
} from "@/core/state/store-binding";
import {
  bindRegistries,
  unbindRegistries,
  bindClient,
  unbindClient,
} from "./client-binding";
import { EmbedPortalProvider } from "./portal-container";
import { SpEmbedConfigContext } from "./SpEmbedConfigContext";
import { initStoreOnce } from "./initStoreOnce";
import type { SignalpilotClient } from "./types";

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

  // Synchronously bind the client store during render so that non-hook code
  // (getRuntimeManager, API headers) can read from it immediately.
  // Re-bind on every render to handle React Strict Mode's unmount/remount
  // (cleanup effect pops the stack; next render must re-push).
  if (getCurrentStore() !== client.store) {
    bindStore(client.store);
    bindRegistries(client.registries);
    bindClient(client);
  }

  if (!initDone.current) {
    initDone.current = true;
    initStoreOnce(client.store, options);
  }

  // Cleanup: pop the bind stack when unmounting. On Strict Mode remount,
  // the render-phase check above re-pushes before children see stale state.
  useEffect(() => {
    // Re-bind in effect too, in case the render-phase bind was for a
    // previous render that got discarded (concurrent mode).
    if (getCurrentStore() !== client.store) {
      bindStore(client.store);
      bindRegistries(client.registries);
      bindClient(client);
    }

    return () => {
      if (getCurrentStore() === client.store) {
        unbindClient(client);
        unbindRegistries(client.registries);
        unbindStore(client.store);
      }
    };
  }, [client, client.store, client.registries]);

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
