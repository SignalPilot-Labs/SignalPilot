import type { SignalpilotClient } from "@/embed/types";
import type { NotebookConfig } from "./notebook-context";

/**
 * Shared boot types and helpers. The boot entry point is boot-runtime.ts.
 * Import from there in application code; this module only breaks the cycle
 * between the boot variants.
 */

export type BootPhase = "health" | "notion" | "ready";

export class NotebookBootUserError extends Error {
  constructor(message: string) {
    super(message);
    this.name = "NotebookBootUserError";
  }
}

export interface NotebookStaticData {
  filename?: string;
  code?: string;
  session?: unknown;
  notebook?: unknown;
  rawFallback?: boolean;
  /** Gateway auth token resolved at boot (Clerk JWT in cloud, "" in local).
   * Handed to the editor so its own gateway /api calls authenticate. */
  gatewayToken?: string;
}

export interface BootResult {
  client: SignalpilotClient;
  staticData: NotebookStaticData;
}

export function resolveRuntimeBase(config: NotebookConfig): string {
  const base = config.notebookProxyUrl ?? config.gatewayUrl;
  if (base) return base.replace(/\/$/, "");
  return typeof window === "undefined" ? "" : window.location.origin;
}
