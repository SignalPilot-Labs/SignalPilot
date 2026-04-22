"use client";

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

/**
 * Authenticated fetch against the backend API.
 * Accepts a `getToken` function (from Clerk's `useAuth()`) so the token is
 * always fresh — never stale from a prior render.
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

  const token = await getToken();
  if (!token) {
    throw new Error("No auth token available. Please sign in.");
  }

  const headers: Record<string, string> = {
    "Content-Type": "application/json",
    Authorization: `Bearer ${token}`,
    ...(options?.headers as Record<string, string>),
  };

  const res = await fetch(`${BACKEND_URL}${path}`, {
    ...options,
    headers,
  });

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
  getSubscription(): Promise<SubscriptionResponse>;
  createCheckoutSession(
    planTier: string,
    successUrl: string,
    cancelUrl: string,
  ): Promise<{ checkout_url: string }>;
  createPortalSession(returnUrl: string): Promise<{ portal_url: string }>;
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

  return {
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

    getSubscription: () =>
      backendFetch<SubscriptionResponse>("/api/v1/billing/subscription", getToken),

    createCheckoutSession: (planTier: string, successUrl: string, cancelUrl: string) =>
      backendFetch<{ checkout_url: string }>("/api/v1/billing/checkout", getToken, {
        method: "POST",
        body: JSON.stringify({
          plan_tier: planTier,
          success_url: successUrl,
          cancel_url: cancelUrl,
        }),
      }),

    createPortalSession: (returnUrl: string) =>
      backendFetch<{ portal_url: string }>("/api/v1/billing/portal", getToken, {
        method: "POST",
        body: JSON.stringify({ return_url: returnUrl }),
      }),

    getUsageSummary: () =>
      backendFetch<UsageSummaryResponse>("/api/v1/usage/summary", getToken),

    getUsageDaily: (days = 30) =>
      backendFetch<DailyUsageResponse>(`/api/v1/usage/daily?days=${days}`, getToken),

    getUsageByKey: () =>
      backendFetch<KeyUsageByKeyResponse>("/api/v1/usage/by-key", getToken),
  };
}
