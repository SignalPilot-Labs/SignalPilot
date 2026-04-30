"use client";

import { useMemo } from "react";
import { useAuth } from "@clerk/nextjs";

// ---------------------------------------------------------------------------
// Config
// ---------------------------------------------------------------------------

const BACKEND_URL = process.env.NEXT_PUBLIC_BACKEND_URL ?? "";

// ---------------------------------------------------------------------------
// Types
// ---------------------------------------------------------------------------

export interface ApiKeyResponse {
  id: string;
  name: string;
  prefix: string;
  scopes: string[];
  created_at: string;
  last_used_at: string | null;
}

export interface ApiKeyCreatedResponse extends ApiKeyResponse {
  raw_key: string;
}

export interface MeResponse {
  user_id: string;
  email: string | null;
  first_name: string | null;
  last_name: string | null;
  image_url: string | null;
}

export interface SubscriptionResponse {
  plan_tier: string;
  status: string;
  stripe_subscription_id: string | null;
  current_period_end: string | null;
  max_api_keys: number;
  pending_downgrade_to: string | null;
  pending_downgrade_date: string | null;
  cancel_at_period_end: boolean;
  cancel_date: string | null;
}

export interface PlanPrice {
  price_id: string;
  amount: number; // cents
  currency: string;
  interval: "month" | "year";
}

export interface PlanInfo {
  tier: string;
  name: string;
  description: string;
  features: string[];
  highlight_color: string;
  prices: PlanPrice[];
}

export interface PlansResponse {
  plans: PlanInfo[];
  publishable_key: string;
}

export interface UsageSummaryResponse {
  total_requests: number;
  total_requests_today: number;
  total_requests_7d: number;
  total_requests_30d: number;
  daily_limit: number;
  daily_used: number;
  daily_reset_at: string;
  active_keys: number;
  last_activity_at: string | null;
}

export interface DailyUsagePoint {
  date: string;
  requests: number;
}

export interface DailyUsageResponse {
  points: DailyUsagePoint[];
}

export interface KeyUsageEntry {
  key_id: string;
  key_name: string;
  total_requests: number;
  last_7d: number;
  last_used_at: string | null;
}

export interface KeyUsageByKeyResponse {
  keys: KeyUsageEntry[];
}

// ---------------------------------------------------------------------------
// Core fetch
// ---------------------------------------------------------------------------

// ---------------------------------------------------------------------------
// Token cache — Clerk tokens are valid for 60s, no need to fetch on every call.
// Uses globalThis to survive Turbopack tree-shaking of module-level vars.
// ---------------------------------------------------------------------------

interface TokenCache {
  token: string | null;
  exp: number;
}

const CACHE_KEY = "__sp_token_cache";
const TOKEN_CACHE_MARGIN_MS = 5_000;

function _getCache(): TokenCache {
  const g = globalThis as Record<string, unknown>;
  if (!g[CACHE_KEY]) {
    g[CACHE_KEY] = { token: null, exp: 0 };
  }
  return g[CACHE_KEY] as TokenCache;
}

function _parseJwtExp(token: string): number {
  try {
    const payload = JSON.parse(atob(token.split(".")[1]));
    return (payload.exp ?? 0) * 1000;
  } catch {
    return 0;
  }
}

async function _getCachedToken(
  getToken: () => Promise<string | null>,
): Promise<string | null> {
  const cache = _getCache();
  if (cache.token && Date.now() < cache.exp - TOKEN_CACHE_MARGIN_MS) {
    return cache.token;
  }
  const token = await getToken();
  if (token) {
    cache.token = token;
    cache.exp = _parseJwtExp(token);
  }
  return token;
}

function _invalidateCache(): void {
  const cache = _getCache();
  cache.token = null;
  cache.exp = 0;
}

/**
 * Authenticated fetch against the backend API.
 * Caches the Clerk JWT until near-expiry. On 401, invalidates the cache,
 * fetches a fresh token, and retries once.
 */
export async function backendFetch<T>(
  path: string,
  getToken: () => Promise<string | null>,
  options?: RequestInit,
): Promise<T> {
  if (!BACKEND_URL) {
    throw new Error(
      "NEXT_PUBLIC_BACKEND_URL is not set. Backend features are unavailable.",
    );
  }

  const doFetch = async (token: string): Promise<Response> => {
    const headers: Record<string, string> = {
      "Content-Type": "application/json",
      Authorization: `Bearer ${token}`,
      ...(options?.headers as Record<string, string>),
    };
    return fetch(`${BACKEND_URL}${path}`, { ...options, headers });
  };

  // Try with cached token first
  const token = await _getCachedToken(getToken);
  if (!token) {
    throw new Error("No auth token available. Please sign in.");
  }

  let res = await doFetch(token);

  // On 401, invalidate cache, get fresh token, retry once
  if (res.status === 401) {
    _invalidateCache();
    const freshToken = await _getCachedToken(getToken);
    if (freshToken) {
      res = await doFetch(freshToken);
    }
  }

  if (!res.ok) {
    const body = await res.text().catch(() => res.statusText);
    throw new Error(`Backend ${res.status}: ${body}`);
  }

  if (res.status === 204) return undefined as T;
  return res.json() as Promise<T>;
}

// ---------------------------------------------------------------------------
// useBackendClient hook — convenience wrapper that closes over getToken
// ---------------------------------------------------------------------------

export interface BackendClient {
  getMe(): Promise<MeResponse>;
  getApiKeys(): Promise<ApiKeyResponse[]>;
  createApiKey(name: string, scopes: string[]): Promise<ApiKeyCreatedResponse>;
  deleteApiKey(keyId: string): Promise<void>;
  getPlans(): Promise<PlansResponse>;
  previewProration(priceId: string): Promise<{
    amount_due: number;
    currency: string;
    credit: number;
    new_charge: number;
    immediate: boolean;
    effective_date: string | null;
  }>;
  getSubscription(): Promise<SubscriptionResponse>;
  createCheckoutSession(
    priceId: string,
    successUrl: string,
    cancelUrl: string,
  ): Promise<{ checkout_url: string | null; action: "checkout" | "updated" }>;
  createPortalSession(returnUrl: string): Promise<{ portal_url: string }>;
  cancelSubscription(): Promise<{ status: string; cancel_date: string | null }>;
  reactivateSubscription(): Promise<{ status: string }>;
  getUsageSummary(): Promise<UsageSummaryResponse>;
  getUsageDaily(days?: number): Promise<DailyUsageResponse>;
  getUsageByKey(): Promise<KeyUsageByKeyResponse>;
}

/**
 * Returns a typed backend client whose methods automatically acquire a fresh
 * Clerk JWT on every call. Must be used inside a component (it calls hooks).
 */
export function useBackendClient(): BackendClient {
  const { getToken } = useAuth();

  return useMemo<BackendClient>(() => ({
    getMe: () => backendFetch<MeResponse>("/api/v1/me", getToken),

    getApiKeys: () => backendFetch<ApiKeyResponse[]>("/api/v1/keys", getToken),

    createApiKey: (name: string, scopes: string[]) =>
      backendFetch<ApiKeyCreatedResponse>("/api/v1/keys", getToken, {
        method: "POST",
        body: JSON.stringify({ name, scopes }),
      }),

    deleteApiKey: (keyId: string) =>
      backendFetch<void>(`/api/v1/keys/${keyId}`, getToken, {
        method: "DELETE",
      }),

    getPlans: () =>
      backendFetch<PlansResponse>("/api/v1/billing/plans", getToken),

    previewProration: (priceId: string) =>
      backendFetch<{ amount_due: number; currency: string; credit: number; new_charge: number; immediate: boolean; effective_date: string | null }>(
        "/api/v1/billing/preview-proration", getToken, {
          method: "POST",
          body: JSON.stringify({ price_id: priceId }),
        },
      ),

    getSubscription: () =>
      backendFetch<SubscriptionResponse>("/api/v1/billing/subscription", getToken),

    createCheckoutSession: (priceId: string, successUrl: string, cancelUrl: string) =>
      backendFetch<{ checkout_url: string | null; action: "checkout" | "updated" }>("/api/v1/billing/checkout", getToken, {
        method: "POST",
        body: JSON.stringify({
          price_id: priceId,
          success_url: successUrl,
          cancel_url: cancelUrl,
        }),
      }),

    createPortalSession: (returnUrl: string) =>
      backendFetch<{ portal_url: string }>("/api/v1/billing/portal", getToken, {
        method: "POST",
        body: JSON.stringify({ return_url: returnUrl }),
      }),

    cancelSubscription: () =>
      backendFetch<{ status: string; cancel_date: string | null }>("/api/v1/billing/cancel", getToken, {
        method: "POST",
      }),

    reactivateSubscription: () =>
      backendFetch<{ status: string }>("/api/v1/billing/reactivate", getToken, {
        method: "POST",
      }),

    getUsageSummary: () =>
      backendFetch<UsageSummaryResponse>("/api/v1/usage/summary", getToken),

    getUsageDaily: (days = 30) =>
      backendFetch<DailyUsageResponse>(`/api/v1/usage/daily?days=${days}`, getToken),

    getUsageByKey: () =>
      backendFetch<KeyUsageByKeyResponse>("/api/v1/usage/by-key", getToken),
  }), [getToken]);
}
