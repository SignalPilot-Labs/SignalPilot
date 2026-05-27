import { tryGetNotebookConfig, type NotebookConfig } from "~/components/notebook/notebook-context";
import { Logger } from "@/utils/Logger";
import { Strings } from "@/utils/strings";
import { getRuntimeManager } from "../runtime/config";
import {
  getGatewayBranchId,
  getGatewayProjectId,
} from "./api";
import { waitForConnectionOpen } from "./connection";

/**
 * Wait for the pod to be verified reachable.
 *
 * RuntimeManager.waitForHealthy() resolves once the boot sequence
 * (NotebookBoot or standalone init) confirms the pod responds to
 * health checks. This prevents API calls from firing before the pod
 * connection is established — e.g. after a page refresh where
 * NotebookConfig is set from React props but the pod hasn't been
 * re-verified yet.
 */
async function waitForPodReady(): Promise<void> {
  try {
    const rm = getRuntimeManager();
    if (!rm.isLazy) {
      await rm.waitForHealthy();
    }
  } catch {
    // RuntimeManager not initialized yet (during early boot) — skip
  }
}

interface BaseUrlAndHeaders {
  baseUrl: string;
  headers: Record<string, string>;
}

/**
 * Notebook mode: resolve URL and headers directly from NotebookConfig.
 * Config is already set by React context — no async overhead.
 */
function resolveFromNotebookConfig(config: NotebookConfig): BaseUrlAndHeaders {
  return {
    baseUrl: `${config.gatewayUrl}/notebook/${config.sessionId}/`,
    headers: {
      Authorization: `Bearer ${config.token}`,
      "Content-Type": "application/json",
    },
  };
}

/**
 * Standalone mode: resolve URL and headers from the RuntimeManager.
 * Waits for the runtime to become healthy before returning.
 */
async function resolveFromRuntimeManager(): Promise<BaseUrlAndHeaders> {
  const rm = getRuntimeManager();
  await rm.waitForHealthy();
  const url = rm.httpURL;
  url.search = "";
  url.hash = "";
  return {
    baseUrl: Strings.withTrailingSlash(url.toString()),
    headers: {
      "Content-Type": "application/json",
      ...(await rm.headers()),
    },
  };
}

/**
 * Resolve the base URL and auth headers for API calls.
 *
 * If NotebookConfig is set (notebook mode), uses that — instant, no async overhead.
 * Otherwise delegates to RuntimeManager (standalone mode).
 * Both paths wait for the pod health check before returning.
 */
async function getBaseUrlAndHeaders(): Promise<BaseUrlAndHeaders> {
  const config = tryGetNotebookConfig();
  if (config) {
    await waitForPodReady();
    return resolveFromNotebookConfig(config);
  }
  return resolveFromRuntimeManager();
}

/**
 * Build the full URL for an API call to the notebook pod.
 * Handles base URL trailing slashes and path joining.
 */
function buildURL(baseUrl: string, path: string): string {
  const base = Strings.withTrailingSlash(baseUrl);
  // Normalize: strip leading slash from path so we don't double-up
  const cleanPath = path.replace(/^\//, "");
  return `${base}api/${cleanPath}`;
}

/**
 * Build headers for API calls, including auth, session, and gateway IDs.
 */
function addGatewayHeaders(headers: Record<string, string>): Record<string, string> {
  const projectId = getGatewayProjectId();
  if (projectId) {
    headers["X-Gateway-Project-Id"] = projectId;
    const branchId = getGatewayBranchId();
    if (branchId) {
      headers["X-Gateway-Branch-Id"] = branchId;
    }
  }

  return headers;
}

/**
 * Parse a fetch Response, throwing on HTTP errors.
 */
async function parseResponse<T>(response: Response, url: string): Promise<T> {
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
    return response.json() as Promise<T>;
  }
  return response.text() as unknown as Promise<T>;
}

/**
 * Simple HTTP call to the notebook pod. Waits only for the runtime
 * health check -- no kernel, no WebSocket dependency.
 *
 * Used by: file tree, git panel, dbt panel, project sync, home page.
 *
 * When `body` is provided the request is POST; otherwise GET.
 */
export async function apiCall<T>(
  path: string,
  body?: unknown,
): Promise<T> {
  const { baseUrl, headers } = await getBaseUrlAndHeaders();
  addGatewayHeaders(headers);

  const url = buildURL(baseUrl, path);
  const method = body !== undefined ? "POST" : "GET";

  const response = await fetch(url, {
    method,
    headers,
    body: body !== undefined ? JSON.stringify(body) : undefined,
  }).catch((error) => {
    Logger.error(`Error requesting ${url}`, error);
    throw error;
  });

  return parseResponse<T>(response, url);
}

/**
 * HTTP call that requires the kernel to be connected.
 * Waits for connectionAtom === OPEN before executing.
 * Throws if the connection is not open.
 *
 * Used by: execute, instantiate, autocomplete, format.
 *
 * When `body` is provided the request is POST; otherwise GET.
 */
export async function kernelCall<T>(
  path: string,
  body?: unknown,
): Promise<T> {
  await waitForConnectionOpen();
  return apiCall<T>(path, body);
}

/**
 * POST multipart/form-data to the notebook pod. Waits for the runtime
 * health check like `apiCall`, but sends a FormData body instead of JSON.
 * The browser sets the Content-Type (with boundary) automatically.
 *
 * Used by: file creation (which may include a Blob upload).
 */
export async function apiCallMultipart<T>(
  path: string,
  formData: FormData,
): Promise<T> {
  const { baseUrl, headers } = await getBaseUrlAndHeaders();
  addGatewayHeaders(headers);
  // Let the browser set Content-Type for multipart
  delete headers["Content-Type"];

  const url = buildURL(baseUrl, path);

  const response = await fetch(url, {
    method: "POST",
    headers,
    body: formData,
  }).catch((error) => {
    Logger.error(`Error requesting ${url}`, error);
    throw error;
  });

  return parseResponse<T>(response, url);
}

// ── TTL cache for read-only API calls ─────────────────────────────

const cache = new Map<string, { data: unknown; timestamp: number }>();

/**
 * Cached variant of `apiCall`. Returns a cached result when the same
 * path+body combination was fetched within `ttl` milliseconds (default 5 000).
 */
export async function cachedApiCall<T>(
  path: string,
  body?: unknown,
  opts?: { ttl?: number },
): Promise<T> {
  const key = `${path}:${JSON.stringify(body ?? {})}`;
  const ttl = opts?.ttl ?? 5000;
  const cached = cache.get(key);
  if (cached && Date.now() - cached.timestamp < ttl) {
    return cached.data as T;
  }
  const result = await apiCall<T>(path, body);
  cache.set(key, { data: result, timestamp: Date.now() });
  return result;
}
