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
} from "@/lib/api";
import type { PlanUsage } from "@/lib/api";
import type {
  ConnectionInfo,
  ConnectionHealthStats,
  GatewaySettings,
} from "@/lib/types";

// ── Cache keys (exported for manual invalidation) ────────────────────────────

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
  connectionSchema: (name: string) => `/api/connections/${name}/schema`,
  healthHistory: (name: string) => `/api/connections/${name}/health/history`,
} as const;

// ── Hooks ────────────────────────────────────────────────────────────────────

/** Connection list — stable data, 60s cache. */
export function useConnections() {
  return useSWR<ConnectionInfo[]>(
    SWR_KEYS.connections,
    () => getConnections(),
    { refreshInterval: 0, dedupingInterval: 60_000 },
  );
}

/** All connections health — refreshes every 15s. Pass false to disable fetching entirely. */
export function useConnectionsHealth(enabled: boolean = true) {
  return useSWR<{ connections: ConnectionHealthStats[] }>(
    enabled ? SWR_KEYS.connectionsHealth : null,
    () => getConnectionsHealth(),
    { refreshInterval: enabled ? 15_000 : 0 },
  );
}

/** Health history for a single connection sparkline. */
export function useHealthHistory(name: string | null, window = 3600, bucket = 120) {
  return useSWR(
    name ? SWR_KEYS.healthHistory(name) : null,
    () => getConnectionHealthHistory(name!, window, bucket),
    { refreshInterval: 30_000 },
  );
}

/** Query cache stats — 30s cache. */
export function useCacheStats() {
  return useSWR(
    SWR_KEYS.cacheStats,
    () => getCacheStats(),
    { refreshInterval: 30_000 },
  );
}

/** Schema cache stats — 30s cache. */
export function useSchemaCache() {
  return useSWR(
    SWR_KEYS.schemaCache,
    () => getSchemaCache(),
    { refreshInterval: 30_000 },
  );
}

/** API keys list — 30s cache. */
export function useApiKeys() {
  return useSWR(
    SWR_KEYS.apiKeys,
    () => getApiKeys(),
    { dedupingInterval: 30_000 },
  );
}

/** Plan tier, limits, and current usage — 60s cache. */
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

/** Gateway settings — rarely changes, 5min cache. */
export function useSettings() {
  return useSWR<GatewaySettings>(
    SWR_KEYS.settings,
    () => getSettings(),
    { dedupingInterval: 300_000 },
  );
}

/** Budget sessions. */
export function useBudgets() {
  return useSWR(
    SWR_KEYS.budgets,
    () => getBudgets(),
    { dedupingInterval: 10_000 },
  );
}

/** Audit log. */
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

/** Schema for a single connection — expensive, 5min cache. */
export function useConnectionSchema(name: string | null) {
  return useSWR(
    name ? SWR_KEYS.connectionSchema(name) : null,
    () => getConnectionSchema(name!),
    { dedupingInterval: 300_000, revalidateOnFocus: false },
  );
}

// ── Invalidation helpers ────────────────────────────────────────────────────

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
  // Revalidate all SWR keys — nuclear option
  return mutate(() => true, undefined, { revalidate: true });
}

/** Clear ALL app state on sign-out: SWR cache, localStorage, module state. */
export function clearAppState() {
  // 1. Clear entire SWR cache (no revalidation — data is gone)
  mutate(() => true, undefined, { revalidate: false });

  // 2. Clear all SignalPilot localStorage keys
  try {
    localStorage.removeItem("sp_active_connection");
    localStorage.removeItem("sp_api_key");
    localStorage.removeItem("sp_query_history");
  } catch {}

  // 3. Reset the Clerk token getter in api.ts
  setApiKey(null);
}

// ── Prefetch helper (call on dashboard mount) ───────────────────────────────

export function prefetchCommonData() {
  // Fire these in parallel — SWR deduplicates automatically
  mutate(SWR_KEYS.connections, getConnections(), { revalidate: false });
  mutate(SWR_KEYS.connectionsHealth, getConnectionsHealth(), { revalidate: false });
  mutate(SWR_KEYS.apiKeys, getApiKeys(), { revalidate: false });
  mutate(SWR_KEYS.cacheStats, getCacheStats(), { revalidate: false });
}
