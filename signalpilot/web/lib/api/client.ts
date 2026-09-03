// Core request helpers for the gateway API.
// This module holds authentication state and the shared request function.
// The other api modules import from this module.

export const GATEWAY_URL =
  process.env.NEXT_PUBLIC_GATEWAY_URL || "http://localhost:3300";
const IS_CLOUD_MODE = process.env.NEXT_PUBLIC_DEPLOYMENT_MODE === "cloud";

// The following code gets Clerk tokens in cloud mode.
// auth-context sets the token getter after Clerk loads.
// Early requests wait for Clerk initialization before they use JWT authentication.
let _clerkGetToken: (() => Promise<string | null>) | null = null;
let _resolveClerkReady: (() => void) | null = null;
const _clerkReadyPromise: Promise<void> | null = IS_CLOUD_MODE
  ? new Promise<void>((resolve) => {
      _resolveClerkReady = resolve;
    })
  : null;

export function setClerkTokenGetter(getter: () => Promise<string | null>) {
  _clerkGetToken = getter;
  if (_resolveClerkReady) {
    _resolveClerkReady();
    _resolveClerkReady = null;
  }
}

// The following code gets the local API key automatically.
// sessionStorage contains the key.
// This storage location reduces exposure to persistent XSS.
// The browser removes the key when the tab closes.
if (typeof window !== "undefined" && IS_CLOUD_MODE) {
  sessionStorage.removeItem("sp_api_key");
}

let _localKeyPromise: Promise<string | null> | null = null;

function _fetchLocalKey(): Promise<string | null> {
  if (typeof window === "undefined" || IS_CLOUD_MODE)
    return Promise.resolve(null);
  return fetch("/api/local-key")
    .then((r) => (r.ok ? r.json() : null))
    .then((data: any) => {
      if (data?.key) {
        sessionStorage.setItem("sp_api_key", data.key);
        return data.key as string;
      }
      return null;
    })
    .catch(() => null);
}

function getApiKey(): string | null {
  if (typeof window === "undefined") return null;
  if (IS_CLOUD_MODE) {
    // Cloud mode uses the Clerk JWT, never a stored sp_ key.
    return null;
  }
  const stored = sessionStorage.getItem("sp_api_key");
  if (stored) return stored;
  if (!_localKeyPromise) {
    _localKeyPromise = _fetchLocalKey();
  }
  return null;
}

export function setApiKey(key: string | null) {
  if (key) {
    sessionStorage.setItem("sp_api_key", key);
  } else {
    sessionStorage.removeItem("sp_api_key");
  }
}

// The following function sends API requests.

export async function _getAuthHeader(): Promise<string | null> {
  // In cloud mode, wait for Clerk initialization and then use the JWT.
  if (IS_CLOUD_MODE) {
    if (_clerkReadyPromise && !_clerkGetToken) {
      // Wait up to 10s for Clerk to load — avoids firing unauthenticated requests
      await Promise.race([
        _clerkReadyPromise,
        new Promise((r) => setTimeout(r, 10_000)),
      ]);
    }
    if (_clerkGetToken) {
      const token = await _clerkGetToken();
      if (token) return `Bearer ${token}`;
    }
    return null;
  }
  // In local mode, use the sp_ API key.
  let apiKey = getApiKey();
  if (!apiKey && _localKeyPromise) {
    apiKey = await _localKeyPromise;
  }
  if (apiKey) return `Bearer ${apiKey}`;
  return null;
}

export async function getAuthHeaders(): Promise<Record<string, string>> {
  const auth = await _getAuthHeader();
  const h: Record<string, string> = {};
  if (auth) h["Authorization"] = auth;
  return h;
}

/**
 * Return the raw gateway authentication token without the Bearer prefix.
 * Cloud mode returns the Clerk JWT.
 * Local mode returns the sp_ API key or null when authentication is disabled.
 * The notebook proxy sends this token in the HTTP Authorization header.
 * WebSocket requests use the Sec-WebSocket-Protocol two-token format.
 * The embedded client receives the token through its authToken callback.
 */
export async function getGatewayAuthToken(): Promise<string | null> {
  const header = await _getAuthHeader();
  if (!header) return null;
  return header.startsWith("Bearer ") ? header.slice(7) : header;
}

/** A non-2xx gateway reply. `status` lets callers branch on 404/409/422. */
export class ApiRequestError extends Error {
  status: number;
  body: string;
  constructor(status: number, body: string) {
    super(`${status}: ${body}`);
    this.name = "ApiRequestError";
    this.status = status;
    this.body = body;
  }
}

/** HTTP status of a thrown request error, or null when it is not one. */
export function requestErrorStatus(err: unknown): number | null {
  if (err instanceof ApiRequestError) return err.status;
  if (err instanceof Error) {
    const m = /^(\d{3}):/.exec(err.message);
    if (m) return Number(m[1]);
  }
  return null;
}

export async function request<T>(
  path: string,
  options?: RequestInit,
  _retried = false,
): Promise<T> {
  const authHeader = await _getAuthHeader();
  const headers: Record<string, string> = {
    "Content-Type": "application/json",
    ...(options?.headers as Record<string, string>),
  };
  if (authHeader) {
    headers["Authorization"] = authHeader;
  }
  const res = await fetch(`${GATEWAY_URL}${path}`, {
    ...options,
    headers,
  });
  // Clear stale credentials after a 401 or 403 response and retry once.
  if ((res.status === 401 || res.status === 403) && !_retried) {
    sessionStorage.removeItem("sp_api_key");
    _localKeyPromise = null;
    // In cloud mode, the Clerk token getter provides a fresh token.
    // In local mode, fetch the local key again.
    if (!IS_CLOUD_MODE) {
      _localKeyPromise = _fetchLocalKey();
      await _localKeyPromise;
    }
    return request<T>(path, options, true);
  }
  if (!res.ok) {
    const body = await res.text();
    throw new ApiRequestError(res.status, body);
  }
  if (res.status === 204) return undefined as T;
  return res.json();
}

export async function downloadChatArtifact(
  path: string,
  format: string,
  filename: string,
): Promise<void> {
  const headers = await getAuthHeaders();
  const response = await fetch(`${GATEWAY_URL}${path}`, { headers });
  if (!response.ok) throw new Error(`Download failed (${response.status})`);
  const blob = await response.blob();
  const url = URL.createObjectURL(blob);
  const anchor = document.createElement("a");
  anchor.href = url;
  anchor.download = `${filename.replace(/\.[^.]+$/, "")}.${format}`;
  document.body.appendChild(anchor);
  anchor.click();
  anchor.remove();
  URL.revokeObjectURL(url);
}
