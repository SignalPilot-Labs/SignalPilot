"use client";

import React from "react";

export interface NotebookConfig {
  gatewayUrl: string;
  sessionId: string;
  /** Session access token (from notebook_url ?token= param) */
  token: string;
  /** Local API key for gateway workspace calls */
  apiKey?: string;
  /** Project ID from URL */
  project?: string;
  /** Branch from URL */
  branch?: string;
  /** File path from URL */
  file?: string;
}

const NotebookContext = React.createContext<NotebookConfig | null>(null);

export function NotebookProvider({
  children,
  value,
}: {
  children: React.ReactNode;
  value: NotebookConfig;
}) {
  // Also update the module-level config so non-React code can access it
  React.useEffect(() => {
    setNotebookConfig(value);
  }, [value]);

  return (
    <NotebookContext.Provider value={value}>
      {children}
    </NotebookContext.Provider>
  );
}

export function useNotebookConfig(): NotebookConfig {
  const ctx = React.useContext(NotebookContext);
  if (!ctx)
    throw new Error("useNotebookConfig must be used inside NotebookProvider");
  return ctx;
}

// ── Non-React access (for apiCall and boot-phase code) ──────────

let _config: NotebookConfig | null = null;

export function setNotebookConfig(config: NotebookConfig): void {
  _config = config;
}

export function getNotebookConfig(): NotebookConfig {
  if (!_config) throw new Error("NotebookConfig not set");
  return _config;
}

export function tryGetNotebookConfig(): NotebookConfig | null {
  return _config;
}
