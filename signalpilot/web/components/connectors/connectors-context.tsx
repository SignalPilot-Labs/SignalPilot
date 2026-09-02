"use client";

// Connectors data layer for React: one provider chooses the API (live or
// fixture), one store hook owns the list and applies optimistic updates.

import {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useMemo,
  useRef,
  useState,
  type ReactNode,
} from "react";
import type { Connector, OrgPolicy } from "~/lib/api/mcp-connectors";
import { sortConnectors } from "~/lib/mcp-connectors-state";
import { liveConnectorsApi, type ConnectorsApi } from "./connectors-api";

type ConnectorsStore = {
  api: ConnectorsApi;
  /** True when running against the in-memory fixture (no gateway). */
  fixture: boolean;
  connectors: Connector[];
  policy: OrgPolicy | null;
  isAdmin: boolean;
  /** Organization display name ("Everyone in Acme"); null until known. */
  orgName: string | null;
  /** The caller's user id when the surface knows it (fixture); used for "you". */
  currentUserId: string | null;
  loading: boolean;
  error: string | null;
  reload: () => Promise<void>;
  upsert: (connector: Connector) => void;
  removeLocal: (id: string) => void;
  setPolicy: (policy: OrgPolicy) => void;
};

const ConnectorsContext = createContext<ConnectorsStore | null>(null);

export function ConnectorsProvider({
  api = liveConnectorsApi,
  fixture = false,
  enabled = true,
  currentUserId = null,
  children,
}: {
  api?: ConnectorsApi;
  fixture?: boolean;
  /** False when the feature flag is off: no request is made. */
  enabled?: boolean;
  currentUserId?: string | null;
  children: ReactNode;
}) {
  const [connectors, setConnectors] = useState<Connector[]>([]);
  const [policy, setPolicyState] = useState<OrgPolicy | null>(null);
  const [isAdmin, setIsAdmin] = useState(false);
  const [orgName, setOrgName] = useState<string | null>(null);
  const [loading, setLoading] = useState(enabled);
  const [error, setError] = useState<string | null>(null);
  const requestId = useRef(0);

  const reload = useCallback(async () => {
    if (!enabled) {
      setLoading(false);
      return;
    }
    const id = ++requestId.current;
    try {
      const response = await api.list();
      if (id !== requestId.current) return;
      setConnectors(sortConnectors(response.connectors));
      setPolicyState(response.policy);
      setIsAdmin(response.is_admin);
      setOrgName(response.org_name ?? null);
      setError(null);
    } catch (caught) {
      if (id !== requestId.current) return;
      setError((caught as Error).message || "We couldn't load your connectors.");
    } finally {
      if (id === requestId.current) setLoading(false);
    }
  }, [api, enabled]);

  useEffect(() => {
    void reload();
  }, [reload]);

  const upsert = useCallback((connector: Connector) => {
    setConnectors((current) => {
      const exists = current.some((c) => c.id === connector.id);
      const next = exists
        ? current.map((c) => (c.id === connector.id ? { ...c, ...connector } : c))
        : [...current, connector];
      return sortConnectors(next);
    });
  }, []);

  const removeLocal = useCallback((id: string) => {
    setConnectors((current) => current.filter((c) => c.id !== id));
  }, []);

  const value = useMemo<ConnectorsStore>(
    () => ({
      api,
      fixture,
      connectors,
      policy,
      isAdmin,
      orgName,
      currentUserId,
      loading,
      error,
      reload,
      upsert,
      removeLocal,
      setPolicy: setPolicyState,
    }),
    [api, fixture, connectors, policy, isAdmin, orgName, currentUserId, loading, error, reload, upsert, removeLocal],
  );

  return (
    <ConnectorsContext.Provider value={value}>{children}</ConnectorsContext.Provider>
  );
}

export function useConnectors(): ConnectorsStore {
  const value = useContext(ConnectorsContext);
  if (!value) throw new Error("ConnectorsProvider is missing");
  return value;
}

/** Null-safe variant for surfaces (the chat) that may render without the provider. */
export function useOptionalConnectors(): ConnectorsStore | null {
  return useContext(ConnectorsContext);
}
