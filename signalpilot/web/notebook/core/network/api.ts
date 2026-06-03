import { createSpClient } from "@/packages/sp-api";
import { Logger } from "../../utils/Logger";
import { Strings } from "../../utils/strings";
import { getCurrentStore } from "../state/store-binding";
import { getRuntimeManager } from "../runtime/config";
import type { RuntimeManager } from "../runtime/runtime";
import {
  gatewayProjectIdAtom,
  gatewayBranchIdAtom,
  GATEWAY_PROJECT_STORAGE_KEY,
  GATEWAY_BRANCH_STORAGE_KEY,
} from "./gateway-state";

// ── Gateway project ID ──────────────────────────────────────────
// Accessors delegate to per-client Jotai atoms via getCurrentStore().
// localStorage persistence stays on the set path — standalone path writes are
// reflected across page reloads; embed callers that want isolation should not
// call setGatewayProjectId (or should pre-write the atom before mounting).

export function getGatewayProjectId(): string | null {
  return getCurrentStore().get(gatewayProjectIdAtom);
}

export function setGatewayProjectId(id: string | null): void {
  getCurrentStore().set(gatewayProjectIdAtom, id);
  if (typeof localStorage !== "undefined") {
    if (id) {
      localStorage.setItem(GATEWAY_PROJECT_STORAGE_KEY, id);
    } else {
      localStorage.removeItem(GATEWAY_PROJECT_STORAGE_KEY);
    }
  }
}

// ── Gateway branch ID ──────────────────────────────────────────

export function getGatewayBranchId(): string | null {
  return getCurrentStore().get(gatewayBranchIdAtom);
}

export function setGatewayBranchId(id: string | null): void {
  getCurrentStore().set(gatewayBranchIdAtom, id);
  if (typeof localStorage !== "undefined") {
    if (id) {
      localStorage.setItem(GATEWAY_BRANCH_STORAGE_KEY, id);
    } else {
      localStorage.removeItem(GATEWAY_BRANCH_STORAGE_KEY);
    }
  }
}

function getBaseUriWithoutQueryParams(): string {
  // Remove query params and hash
  const url = getRuntimeManager().httpURL;
  url.search = "";
  url.hash = "";
  return url.toString();
}

/**
 * Build a full API URL respecting --base-url.
 * Use this for custom fetch() calls instead of hard-coded "/api/..." paths.
 * e.g. spApiUrl("/git/status") → "/notebook/{sid}/api/git/status"
 */
export function spApiUrl(path: string): string {
  try {
    const base = Strings.withTrailingSlash(getBaseUriWithoutQueryParams());
    return `${base}api${path}`;
  } catch {
    // Runtime not ready yet — derive base from the page URL.
    // When served at /notebook/{session_id}/, this gives the correct proxy prefix.
    const pathname = window.location.pathname;
    const match = pathname.match(/^(\/notebook\/[^/]+\/)/);
    if (match) {
      return `${match[1]}api${path}`;
    }
    return `/api${path}`;
  }
}

/**
 * Wrapper around fetch that adds XSRF token and session ID to the request and
 * strong types.
 */
export const API = {
  async post<REQ, RESP = null>(
    url: string,
    body: REQ,
    opts: {
      headers?: Record<string, string>;
      baseUrl?: string;
      signal?: AbortSignal;
    } = {},
  ): Promise<RESP> {
    const baseUrl = Strings.withTrailingSlash(
      opts.baseUrl ?? getBaseUriWithoutQueryParams(),
    );
    const fullUrl = `${baseUrl}api${url}`;
    return fetch(fullUrl, {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
        ...(await API.headers()),
        ...opts.headers,
      },
      body: JSON.stringify(body),
      signal: opts.signal,
    })
      .then(async (response) => {
        const isJson = response.headers
          .get("Content-Type")
          ?.startsWith("application/json");
        if (!response.ok) {
          const errorBody = isJson
            ? await response.json()
            : await response.text();
          throw new Error(response.statusText, { cause: errorBody });
        }
        if (isJson) {
          return response.json() as RESP;
        }
        return response.text() as unknown as RESP;
      })
      .catch((error) => {
        // Catch and rethrow
        Logger.error(`Error requesting ${fullUrl}`, error);
        throw error;
      });
  },
  async get<RESP = null>(
    url: string,
    opts: {
      headers?: Record<string, string>;
      baseUrl?: string;
    } = {},
  ): Promise<RESP> {
    const baseUrl = Strings.withTrailingSlash(
      opts.baseUrl ?? getBaseUriWithoutQueryParams(),
    );
    const fullUrl = `${baseUrl}api${url}`;
    return fetch(fullUrl, {
      method: "GET",
      headers: {
        ...(await API.headers()),
        ...opts.headers,
      },
    })
      .then((response) => {
        if (!response.ok) {
          throw new Error(response.statusText);
        }
        if (
          response.headers.get("Content-Type")?.startsWith("application/json")
        ) {
          return response.json() as RESP;
        }
        return null as RESP;
      })
      .catch((error) => {
        // Catch and rethrow
        Logger.error(`Error requesting ${fullUrl}`, error);
        throw error;
      });
  },
  async headers() {
    const runtimeManager = getRuntimeManager();
    return runtimeManager.headers();
  },
  handleResponse: <T>(response: {
    data?: T | undefined;
    error?: Record<string, unknown>;
    response: Response;
  }): Promise<T> => {
    if (response.error) {
      // oxlint-disable-next-line typescript/prefer-promise-reject-errors
      return Promise.reject(response.error);
    }
    return Promise.resolve(response.data as T);
  },
  handleResponseReturnNull: (response: {
    error?: Record<string, unknown>;
    response: Response;
  }): Promise<null> => {
    if (response.error) {
      // oxlint-disable-next-line typescript/prefer-promise-reject-errors
      return Promise.reject(response.error);
    }
    return Promise.resolve(null);
  },
};

export function createClientWithRuntimeManager(runtimeManager: RuntimeManager) {
  const spClient = createSpClient({
    baseUrl: runtimeManager.httpURL.toString(),
  });

  spClient.use({
    onRequest: async (req) => {
      const headers = await runtimeManager.headers();

      for (const [key, value] of Object.entries(headers)) {
        req.headers.set(key, value);
      }

      // Inject gateway project/branch IDs for dbt project operations.
      const projectId = getGatewayProjectId();
      if (projectId) {
        req.headers.set("X-Gateway-Project-Id", projectId);
        const branchId = getGatewayBranchId();
        if (branchId) {
          req.headers.set("X-Gateway-Branch-Id", branchId);
        }
      }

      return req;
    },
  });

  return spClient;
}
