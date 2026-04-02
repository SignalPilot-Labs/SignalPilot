"use client";

import {
  createContext,
  useContext,
  useState,
  useEffect,
  useCallback,
  type ReactNode,
} from "react";
import { getConnections } from "@/lib/api";
import type { ConnectionInfo } from "@/lib/types";

const STORAGE_KEY = "sp_active_connection";

interface ConnectionContextValue {
  connections: ConnectionInfo[];
  selectedConn: string;
  setSelectedConn: (name: string) => void;
  refreshConnections: () => Promise<void>;
  loading: boolean;
}

const ConnectionContext = createContext<ConnectionContextValue>({
  connections: [],
  selectedConn: "",
  setSelectedConn: () => {},
  refreshConnections: async () => {},
  loading: true,
});

export function ConnectionProvider({ children }: { children: ReactNode }) {
  const [connections, setConnections] = useState<ConnectionInfo[]>([]);
  const [selectedConn, setSelectedConnState] = useState<string>("");
  const [loading, setLoading] = useState(true);

  const setSelectedConn = useCallback((name: string) => {
    setSelectedConnState(name);
    try {
      localStorage.setItem(STORAGE_KEY, name);
    } catch {}
  }, []);

  const refreshConnections = useCallback(async () => {
    try {
      const conns = await getConnections();
      setConnections(conns);
      // If current selection is gone or empty, pick first
      const currentName =
        selectedConn ||
        (() => {
          try {
            return localStorage.getItem(STORAGE_KEY) || "";
          } catch {
            return "";
          }
        })();
      const stillExists = conns.some((c) => c.name === currentName);
      if (!stillExists && conns.length > 0) {
        setSelectedConn(conns[0].name);
      } else if (stillExists && !selectedConn) {
        setSelectedConnState(currentName);
      }
    } catch {
    } finally {
      setLoading(false);
    }
  }, [selectedConn, setSelectedConn]);

  // Initial load — restore from localStorage then fetch
  useEffect(() => {
    try {
      const stored = localStorage.getItem(STORAGE_KEY);
      if (stored) setSelectedConnState(stored);
    } catch {}
    getConnections()
      .then((conns) => {
        setConnections(conns);
        const stored = (() => {
          try {
            return localStorage.getItem(STORAGE_KEY) || "";
          } catch {
            return "";
          }
        })();
        const exists = conns.some((c) => c.name === stored);
        if (exists) {
          setSelectedConnState(stored);
        } else if (conns.length > 0) {
          setSelectedConn(conns[0].name);
        }
      })
      .catch(() => {})
      .finally(() => setLoading(false));
  }, []); // eslint-disable-line react-hooks/exhaustive-deps

  return (
    <ConnectionContext.Provider
      value={{
        connections,
        selectedConn,
        setSelectedConn,
        refreshConnections,
        loading,
      }}
    >
      {children}
    </ConnectionContext.Provider>
  );
}

export function useConnection() {
  return useContext(ConnectionContext);
}
