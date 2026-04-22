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
  };
}
