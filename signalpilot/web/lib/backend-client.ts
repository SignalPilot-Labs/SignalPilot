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

export type SubscriptionTier = "free" | "team" | "scale" | "enterprise";

export type BillingInterval = "month" | "year";

/** The full entitlement row from `GET /api/v1/billing/subscription`. */
export interface SubscriptionResponse {
  plan_tier: SubscriptionTier;
  status: string;
  /** The backend has already applied the billable rule (status, tier, grace). */
  is_billable: boolean;
  stripe_subscription_id: string | null;
  current_period_end: string | null;
  billing_interval: BillingInterval;
  included_seats: number;
  included_models: number;
  included_eval_runs: number;
  included_credits: number;
  managed: boolean;
  enterprise_flags: Record<string, unknown>;
  contract: Record<string, unknown> | null;
  grace_until: string | null;
  pending_downgrade_to: string | null;
  pending_downgrade_date: string | null;
  cancel_at_period_end: boolean;
  cancel_date: string | null;
}

export type PaidTier = "team" | "scale" | "enterprise";

export interface PlanPrice {
  price_id: string;
  lookup_key: string | null;
  amount: number; // cents
  currency: string;
  interval: BillingInterval;
}

/** One plan from `GET /api/v1/billing/plans`: Stripe product joined with the static rate table. */
export interface PlanInfo {
  tier: PaidTier;
  name: string;
  description: string;
  monthly_fee_cents: number;
  included_seats: number;
  included_models: number;
  included_eval_runs: number;
  included_credits: number;
  seat_month_credits: number;
  managed_from_cents: number;
  prices: PlanPrice[];
}

/** The fixed credit rate card as the backend publishes it. */
export interface RateCard {
  credit_cents: number;
  thread_credits: number;
  query_credits: number;
  model_month_credits: number;
  eval_run_credits: number;
  seat_month_credits: number;
  enterprise_seat_month_credits: number;
  token_credits_per_dollar: number;
  overage_cents_per_credit: number;
}

export interface PlansResponse {
  plans: PlanInfo[];
  rates: RateCard;
  publishable_key: string;
}

export interface CheckoutResponse {
  checkout_url: string | null;
  /** "checkout" redirects to Stripe; "updated" changed the plan in place. */
  action: "checkout" | "updated";
}

export interface ProrationPreviewResponse {
  amount_due: number; // cents; positive = charge, negative = credit
  currency: string;
  credit: number;
  new_charge: number;
  immediate: boolean;
  effective_date: string | null;
}

export interface AllowanceUse {
  used: number;
  included: number;
}

/** Credits consumed for one unit this period, with the metered quantity behind them. */
export interface UnitConsumption {
  credits: number;
  quantity: number;
  rows: number;
}

/** `GET /api/v1/usage/summary`: the open period read from the credit ledger. */
export interface UsageSummaryResponse {
  period_start: string;
  period_end: string;
  plan_tier: SubscriptionTier;
  is_billable: boolean;
  included_credits: number;
  granted: number;
  purchased: number;
  consumed: number;
  consumed_by_unit: Record<string, UnitConsumption>;
  returned: number;
  expired: number;
  available: number;
  overage: number;
  overage_cents: number;
  allowances: {
    seats: AllowanceUse;
    models: AllowanceUse;
    eval_runs: AllowanceUse;
  };
}

/** One UTC day of consumption from `GET /api/v1/usage/daily`. */
export interface DailyUsagePoint {
  date: string; // YYYY-MM-DD
  credits: number;
  by_unit: Record<string, number>;
}

export interface DailyUsageResponse {
  points: DailyUsagePoint[];
}

/**
 * One user's consumption in a period, from `GET /api/v1/usage/by-user` and
 * `GET /api/v1/usage/me`. `user_id` is null for unattributed rows, which the
 * backend labels "System / scheduled".
 */
export interface UsageByUserRow {
  user_id: string | null;
  name: string | null;
  email: string | null;
  credits_consumed: number;
  threads: number;
  queries: number;
  tokens_in: number;
  tokens_out: number;
  tokens_cache_read: number;
  token_credits: number;
}

/** `GET /api/v1/usage/by-user?period=YYYY-MM-01` (admin only). */
export interface UsageByUserResponse {
  period_start: string;
  period_end: string;
  rows: UsageByUserRow[];
}

/**
 * `GET /api/v1/usage/me?period=`: the caller's own row in the same shape,
 * with no org totals. Some backends return the row inline, others under
 * `rows`; `usageMeRow()` reads both.
 */
export interface UsageMeResponse {
  period_start: string;
  period_end: string;
  rows?: UsageByUserRow[];
  row?: UsageByUserRow | null;
}

/** The caller's row out of a `usage/me` answer, or null when nothing was consumed. */
export function usageMeRow(data: UsageMeResponse | null | undefined): UsageByUserRow | null {
  if (!data) return null;
  if (data.row) return data.row;
  if (Array.isArray(data.rows) && data.rows.length > 0) return data.rows[0];
  const inline = data as Partial<UsageByUserRow>;
  if (typeof inline.credits_consumed === "number") return inline as UsageByUserRow;
  return null;
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
    const payload = JSON.parse(atob(token.split(".")[1])) as any;
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
  previewProration(priceId: string): Promise<ProrationPreviewResponse>;
  getSubscription(): Promise<SubscriptionResponse>;
  createCheckoutSession(
    priceId: string,
    successUrl: string,
    cancelUrl: string,
  ): Promise<CheckoutResponse>;
  createPortalSession(returnUrl: string): Promise<{ portal_url: string }>;
  cancelSubscription(): Promise<{ status: string; cancel_date: string | null }>;
  reactivateSubscription(): Promise<{ status: string }>;
  getUsageSummary(): Promise<UsageSummaryResponse>;
  getUsageDaily(days?: number): Promise<DailyUsageResponse>;
  /** Admin only. `period` is the first day of the month, YYYY-MM-01; omitted = open period. */
  getUsageByUser(period?: string): Promise<UsageByUserResponse>;
  /** Any member: their own consumption for the period. */
  getUsageMe(period?: string): Promise<UsageMeResponse>;
}

function periodQuery(period?: string): string {
  return period ? `?period=${encodeURIComponent(period)}` : "";
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
      backendFetch<ProrationPreviewResponse>("/api/v1/billing/preview-proration", getToken, {
        method: "POST",
        body: JSON.stringify({ price_id: priceId }),
      }),

    getSubscription: () =>
      backendFetch<SubscriptionResponse>("/api/v1/billing/subscription", getToken),

    createCheckoutSession: (priceId: string, successUrl: string, cancelUrl: string) =>
      backendFetch<CheckoutResponse>("/api/v1/billing/checkout", getToken, {
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

    getUsageByUser: (period?: string) =>
      backendFetch<UsageByUserResponse>(`/api/v1/usage/by-user${periodQuery(period)}`, getToken),

    getUsageMe: (period?: string) =>
      backendFetch<UsageMeResponse>(`/api/v1/usage/me${periodQuery(period)}`, getToken),

  }), [getToken]);
}
