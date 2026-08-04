"use client";

import useSWR, { mutate } from "swr";
import {
  getConnections,
  getConnectionsHealth,
  getConnectionHealthHistory,
  getCacheStats,
  getSchemaCache,
  getAudit,
  getApiKeys,
  getSettings,
  getBudgets,
  getConnectionSchema,
  getPlan,
  setApiKey,
  listKnowledge,
  getKnowledgeUsage,
  getKnowledgeRetrievals,
  listKnowledgeEdits,
  listReports,
  getReport,
} from "~/lib/api";
import type { PlanUsage } from "~/lib/api";
import type {
  ConnectionInfo,
  ConnectionHealthStats,
  GatewaySettings,
  KnowledgeDoc,
  KnowledgeEdit,
  KnowledgeUsage,
  RetrievalStats,
  Report,
  ReportSummary,
} from "~/lib/types";

// The following constants define cache keys.

export const SWR_KEYS = {
  connections: "/api/connections",
  connectionsHealth: "/api/connections/health",
  cacheStats: "/api/cache/stats",
  schemaCache: "/api/schema/cache",
  apiKeys: "/api/keys",
  plan: "/api/plan",
  settings: "/api/settings",
  budgets: "/api/budgets",
  audit: (params?: string) => `/api/audit${params ? `?${params}` : ""}`,
  auditStats: "/api/audit/stats",
  connectionSchema: (name: string) => `/api/connections/${name}/schema`,
  healthHistory: (name: string) => `/api/connections/${name}/health/history`,
  knowledge: (qs?: string) => `/api/knowledge${qs ? `?${qs}` : ""}`,
  knowledgeUsage: "/api/knowledge/usage",
  knowledgeRetrievals: (days: number) => `/api/knowledge/retrievals?since_days=${days}`,
  knowledgeDoc: (id: string) => `/api/knowledge/${id}`,
  knowledgeEdits: (id: string) => `/api/knowledge/${id}/edits`,
  reports: (qs?: string) => `/api/reports${qs ? `?${qs}` : ""}`,
  report: (id: string) => `/api/reports/${id}`,
} as const;

// The following functions define data hooks.

/** Cache the connection list for 60 seconds. */
export function useConnections() {
  return useSWR<ConnectionInfo[]>(
    SWR_KEYS.connections,
    () => getConnections(),
    { refreshInterval: 0, dedupingInterval: 60_000 },
  );
}

/** Refresh health data for all connections every 15 seconds. Pass false to disable requests. */
export function useConnectionsHealth(enabled: boolean = true) {
  return useSWR<{ connections: ConnectionHealthStats[] }>(
    enabled ? SWR_KEYS.connectionsHealth : null,
    () => getConnectionsHealth(),
    { refreshInterval: enabled ? 15_000 : 0 },
  );
}

/** Return health history for one connection sparkline. */
export function useHealthHistory(name: string | null, window = 3600, bucket = 120) {
  return useSWR(
    name ? SWR_KEYS.healthHistory(name) : null,
    () => getConnectionHealthHistory(name!, window, bucket),
    { refreshInterval: 30_000 },
  );
}

/** Cache query statistics for 30 seconds. */
export function useCacheStats() {
  return useSWR(
    SWR_KEYS.cacheStats,
    () => getCacheStats(),
    { refreshInterval: 30_000 },
  );
}

/** Cache schema statistics for 30 seconds. */
export function useSchemaCache() {
  return useSWR(
    SWR_KEYS.schemaCache,
    () => getSchemaCache(),
    { refreshInterval: 30_000 },
  );
}

/** Cache the API key list for 30 seconds. */
export function useApiKeys() {
  return useSWR(
    SWR_KEYS.apiKeys,
    () => getApiKeys(),
    { dedupingInterval: 30_000 },
  );
}

/** Cache the plan tier, limits, and usage for 60 seconds. */
export function usePlan() {
  return useSWR<PlanUsage>(
    SWR_KEYS.plan,
    () => getPlan(),
    { dedupingInterval: 60_000 },
  );
}

export function invalidatePlan() {
  return mutate(SWR_KEYS.plan);
}

/** Cache gateway settings for five minutes. */
export function useSettings() {
  return useSWR<GatewaySettings>(
    SWR_KEYS.settings,
    () => getSettings(),
    { dedupingInterval: 300_000 },
  );
}

/** Return budget sessions. */
export function useBudgets() {
  return useSWR(
    SWR_KEYS.budgets,
    () => getBudgets(),
    { dedupingInterval: 10_000 },
  );
}

/** Return audit records. */
export function useAudit(params?: { limit?: number; event_type?: string; connection_name?: string }) {
  const searchParams: Record<string, string | number> = {};
  if (params?.limit) searchParams.limit = params.limit;
  if (params?.event_type) searchParams.event_type = params.event_type;
  if (params?.connection_name) searchParams.connection_name = params.connection_name;
  const key = SWR_KEYS.audit(new URLSearchParams(searchParams as Record<string, string>).toString());
  return useSWR(
    key,
    () => getAudit(searchParams),
    { dedupingInterval: 10_000 },
  );
}

export function useAuditStats() {
  return useSWR<{ total: number; mcp_tools: number; queries: number; sql: number; executions: number; blocked: number }>(
    SWR_KEYS.auditStats,
    () => import("~/lib/api").then(({ request }) => request(SWR_KEYS.auditStats)),
    { dedupingInterval: 10_000 },
  );
}

/** Cache the schema for one connection for five minutes. */
export function useConnectionSchema(name: string | null) {
  return useSWR(
    name ? SWR_KEYS.connectionSchema(name) : null,
    () => getConnectionSchema(name!),
    { dedupingInterval: 300_000, revalidateOnFocus: false },
  );
}

// The following hooks access knowledge data.

/** Cache filtered knowledge documents for 30 seconds. */
export function useKnowledgeDocs(filters?: { scope?: string; scope_ref?: string; category?: string; status?: string }) {
  const qs = filters
    ? new URLSearchParams(
        Object.entries(filters).filter(([, v]) => v !== undefined) as [string, string][]
      ).toString()
    : "";
  const key = SWR_KEYS.knowledge(qs || undefined);
  return useSWR<KnowledgeDoc[]>(
    key,
    () => listKnowledge(filters),
    { dedupingInterval: 30_000 },
  );
}

/** Cache knowledge storage usage for 30 seconds. */
export function useKnowledgeUsage() {
  return useSWR<KnowledgeUsage>(
    SWR_KEYS.knowledgeUsage,
    () => getKnowledgeUsage(),
    { dedupingInterval: 30_000 },
  );
}

/** Cache agent retrieval statistics for each document for 30 seconds. */
export function useKnowledgeRetrievals(sinceDays: number) {
  return useSWR<RetrievalStats>(
    SWR_KEYS.knowledgeRetrievals(sinceDays),
    () => getKnowledgeRetrievals(sinceDays),
    { dedupingInterval: 30_000 },
  );
}

/** Fetch knowledge document history when an identifier is available. */
export function useKnowledgeEdits(id: string | null) {
  return useSWR<KnowledgeEdit[]>(
    id ? SWR_KEYS.knowledgeEdits(id) : null,
    () => listKnowledgeEdits(id!),
    { dedupingInterval: 30_000 },
  );
}

/** Invalidate active and pending /api/knowledge cache keys. */
export function invalidateKnowledge() {
  return mutate(
    (key: unknown) => typeof key === "string" && key.startsWith("/api/knowledge"),
    undefined,
    { revalidate: true },
  );
}

// The following hooks access report data.

/** Cache report metadata for 30 seconds. */
export function useReports(filters?: { scope_ref?: string }) {
  const qs = filters?.scope_ref ? `scope_ref=${encodeURIComponent(filters.scope_ref)}` : "";
  return useSWR<ReportSummary[]>(
    SWR_KEYS.reports(qs || undefined),
    () => listReports(filters),
    { dedupingInterval: 30_000 },
  );
}

/** Fetch one report with HTML when an identifier is available. */
export function useReport(id: string | null) {
  return useSWR<Report>(
    id ? SWR_KEYS.report(id) : null,
    () => getReport(id!),
    { dedupingInterval: 30_000 },
  );
}

/** Invalidate all /api/reports cache keys. */
export function invalidateReports() {
  return mutate(
    (key: unknown) => typeof key === "string" && key.startsWith("/api/reports"),
    undefined,
    { revalidate: true },
  );
}

// The following functions invalidate cached data.

export function invalidateConnections() {
  return mutate(SWR_KEYS.connections);
}

export function invalidateHealth() {
  return mutate(SWR_KEYS.connectionsHealth);
}

export function invalidateApiKeys() {
  return mutate(SWR_KEYS.apiKeys);
}

export function invalidateSettings() {
  return mutate(SWR_KEYS.settings);
}

export function invalidateAll() {
// Revalidate all SWR cache keys.
  return mutate(() => true, undefined, { revalidate: true });
}

/** Clear the SWR cache, localStorage, and module state during sign-out. */
export function clearAppState() {
  // Clear the SWR cache without revalidation.
  mutate(() => true, undefined, { revalidate: false });

  // Clear all SignalPilot storage keys.
  try {
    localStorage.removeItem("sp_active_connection");
    localStorage.removeItem("sp_query_history");
    sessionStorage.removeItem("sp_api_key");
  } catch {}

  // Reset the Clerk token getter in api.ts.
  setApiKey(null);
}

// The following function prefetches dashboard data.

export function prefetchCommonData() {
  // Start these requests in parallel. SWR removes duplicate requests.
  mutate(SWR_KEYS.connections, getConnections(), { revalidate: false });
  mutate(SWR_KEYS.connectionsHealth, getConnectionsHealth(), { revalidate: false });
  mutate(SWR_KEYS.apiKeys, getApiKeys(), { revalidate: false });
  mutate(SWR_KEYS.cacheStats, getCacheStats(), { revalidate: false });
}
