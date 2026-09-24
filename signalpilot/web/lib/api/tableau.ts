// Tableau: the org's Tableau site that chat agents can use.
// Thin wrappers over the gateway's /api/tableau/integration routes. The
// shapes mirror the spec's admin/settings contract (snake_case).

import { ApiRequestError, request } from "./client";

export type TableauIntegrationStatus = "ok" | "error" | "unknown";

/** GET /api/tableau/integration. Never carries the token secret. */
export type TableauIntegrationInfo = {
  configured: boolean;
  enabled: boolean;
  /** configured && enabled && status === "ok": chat agents get the tools. */
  active: boolean;
  server_url: string | null;
  site_content_url: string | null;
  site_url: string | null;
  pat_name: string | null;
  status: TableauIntegrationStatus | null;
  last_error: string | null;
  user_name: string | null;
  site_role: string | null;
  /** Epoch seconds. */
  verified_at: number | null;
  /** Epoch seconds. */
  updated_at: number | null;
};

export type TableauIntegrationSave = {
  site_url: string;
  pat_name: string;
  /** Required on the first save; omitted keeps the stored secret. */
  pat_secret?: string;
  enabled?: boolean;
};

const PATH = "/api/tableau/integration";

export const getTableauIntegration = () => request<TableauIntegrationInfo>(PATH);

export const saveTableauIntegration = (payload: TableauIntegrationSave) =>
  request<TableauIntegrationInfo>(PATH, {
    method: "PUT",
    body: JSON.stringify(payload),
  });

export const setTableauIntegrationEnabled = (enabled: boolean) =>
  request<TableauIntegrationInfo>(PATH, {
    method: "PATCH",
    body: JSON.stringify({ enabled }),
  });

export const testTableauIntegration = () =>
  request<TableauIntegrationInfo>(`${PATH}/test`, { method: "POST" });

export const deleteTableauIntegration = () =>
  request<void>(PATH, { method: "DELETE" });

/**
 * The gateway's `detail` text from a failed request, else the fallback.
 * A 400 from PUT carries the Tableau sign-in error here.
 */
export function tableauErrorDetail(err: unknown, fallback: string): string {
  if (err instanceof ApiRequestError) {
    try {
      const parsed = JSON.parse(err.body) as { detail?: unknown };
      if (typeof parsed.detail === "string" && parsed.detail) return parsed.detail;
    } catch {
      // Not JSON: fall through to the raw body.
    }
    if (err.body) return err.body;
  }
  if (err instanceof Error && err.message) return err.message;
  return fallback;
}
