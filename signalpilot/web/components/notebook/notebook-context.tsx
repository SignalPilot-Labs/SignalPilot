"use client";

import React from "react";

export interface NotebookConfig {
  gatewayUrl: string;
  notebookProxyUrl?: string;
  product?: "projects" | "notebooks";
  sessionId: string;
  /**
   * Resolve the gateway auth token (Clerk JWT in cloud, null in local-noauth).
   * Called per request so a refreshed Clerk token is always used. The notebook
   * proxy authenticates this token directly — there is no per-session cookie.
   */
  getToken: () => Promise<string | null>;
  /** Kernel/session ID used inside the notebook runtime. For Notion trails this
   * is also the AI trace thread ID. */
  kernelSessionId?: string;
  /** Local API key for gateway workspace calls */
  apiKey?: string;
  /** Project ID from URL */
  project?: string;
  /** Branch from URL */
  branch?: string;
  /** File path used to initialize the mounted runtime; later files are SPA state. */
  file?: string;
  /** Whether this org has a non-disconnected Notion OAuth installation. */
  notionConnected?: boolean;
  /**
   * Attach to the kernel as a KIOSK (viewer) connection. The kernel's active
   * client — e.g. the chat agent's headless consumer — keeps its connection;
   * this one receives the session replay and live broadcasts alongside it.
   * Used by the chat live notebook panel. Boot is DOCUMENT-FIRST: no health
   * gate, no kernel requirement — the websocket is a background enhancement.
   */
  kioskAttach?: boolean;
  /**
   * Fallback document loader for the kiosk view: returns the notebook source
   * (and optional NotebookSessionV1 outputs snapshot) when the runtime can't
   * serve the document — e.g. the archived document of a finished run whose
   * sandbox is gone. Return null when unavailable.
   */
  loadDocument?: () => Promise<{
    source: string;
    session?: unknown;
  } | null>;
}

const NotebookContext = React.createContext<NotebookConfig | null>(null);

let _config: NotebookConfig | null = null;

export function NotebookProvider({
  children,
  value,
}: {
  children: React.ReactNode;
  value: NotebookConfig;
}) {
  _config = value;
  React.useEffect(() => {
    _config = value;
    return () => {
      if (_config === value) {
        _config = null;
      }
    };
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

export function useOptionalNotebookConfig(): NotebookConfig | null {
  return React.useContext(NotebookContext);
}

// ── Non-React access (for apiCall and boot-phase code) ──────────

export function getNotebookConfig(): NotebookConfig {
  if (!_config) throw new Error("NotebookConfig not set");
  return _config;
}

export function tryGetNotebookConfig(): NotebookConfig | null {
  return _config;
}

// ── Lazily provisioned session id ────────────────────────────────
// A sessionless boot mounts with config.sessionId === "". When the sandbox
// is provisioned later (first Run), the id lands here so URL builders pick
// it up without re-rendering the NotebookProvider (which would remount the
// whole editor).

let _provisionedSessionId = "";

export function setProvisionedSessionId(sessionId: string): void {
  _provisionedSessionId = sessionId;
}

/** The active runtime session id: boot-time if present, else provisioned. */
export function getActiveSessionId(config: NotebookConfig): string {
  return config.sessionId || _provisionedSessionId;
}

export function clearProvisionedSessionId(): void {
  _provisionedSessionId = "";
}
