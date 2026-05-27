import { Deferred } from "@/utils/Deferred";
import { Logger } from "@/utils/Logger";
import { KnownQueryParams } from "../constants";
import { getSessionId, type SessionId } from "../kernel/session";
import { isStaticNotebook } from "../static/static-state";
import type { RuntimeConfig } from "./types";

export class RuntimeManager {
  private initialHealthyCheck = new Deferred<void>();
  private config: RuntimeConfig;
  private lazy: boolean;

  constructor(config: RuntimeConfig, lazy = false) {
    this.config = config;
    this.lazy = lazy;
    // Validate the URL on construction
    try {
      new URL(this.config.url);
    } catch (error) {
      throw new Error(
        `Invalid runtime URL: ${this.config.url}. ${error instanceof Error ? error.message : "Unknown error"}`,
        { cause: error },
      );
    }

    if (!this.lazy) {
      this.init();
    }
  }

  get isLazy(): boolean {
    return this.lazy;
  }

  get httpURL(): URL {
    return new URL(this.config.url);
  }

  get isSameOrigin(): boolean {
    return this.httpURL.origin === window.location.origin;
  }

  /**
   * Resolve the auth token, calling the thunk if necessary.
   * Returns "" when no token is configured.
   * Throws (after logging) if the thunk throws — fail-fast, no fallback.
   */
  async resolveAuthToken(): Promise<string> {
    const { authToken } = this.config;
    if (!authToken) {
      return "";
    }
    if (typeof authToken === "string") {
      return authToken;
    }
    try {
      return await authToken();
    } catch (error) {
      Logger.error(
        `authToken thunk threw: ${error instanceof Error ? error.message : String(error)}`,
        { cause: error },
      );
      throw error;
    }
  }

  /**
   * The base URL of the runtime.
   */
  formatHttpURL(
    path?: string,
    searchParams?: URLSearchParams,
    restrictToKnownQueryParams = true,
  ): URL {
    if (!path) {
      path = "";
    }
    // URL may be something like "http://localhost:8000?auth=123"
    const baseUrl = this.httpURL;
    const currentParams = new URLSearchParams(window.location.search);
    // Copy over search params if provided
    if (searchParams) {
      for (const [key, value] of searchParams.entries()) {
        baseUrl.searchParams.set(key, value);
      }
    }

    for (const [key, value] of currentParams.entries()) {
      if (
        restrictToKnownQueryParams &&
        !Object.values(KnownQueryParams).includes(key)
      ) {
        continue;
      }
      baseUrl.searchParams.set(key, value);
    }

    const cleanPath = baseUrl.pathname.replace(/\/$/, "");
    baseUrl.pathname = `${cleanPath}/${path.replace(/^\//, "")}`;
    baseUrl.hash = "";
    return baseUrl;
  }

  /**
   * Build a WS URL from an HTTP URL string (pure synthesis, no token).
   */
  private buildWsURL(
    path: string,
    searchParams?: URLSearchParams,
  ): URL {
    const url = this.formatHttpURL(
      path,
      searchParams,
      /* restrictToKnownQueryParams =*/ false,
    );
    return asWsUrl(url.toString());
  }

  /**
   * Build a WS URL and append `?access_token=` when cross-origin and the
   * resolved token is non-empty. This is the single source of truth for
   * token attachment on WebSocket / SSE connections.
   */
  async resolveWsURL(path: string, searchParams?: URLSearchParams): Promise<URL> {
    const url = this.buildWsURL(path, searchParams);

    if (!this.isSameOrigin) {
      const token = await this.resolveAuthToken();
      if (token) {
        url.searchParams.set(KnownQueryParams.accessToken, token);
      }
    }

    return url;
  }

  /**
   * The WebSocket URL of the runtime.
   */
  async getWsURL(sessionId: SessionId): Promise<URL> {
    const baseUrl = new URL(this.config.url);
    const searchParams = new URLSearchParams(baseUrl.search);

    // Merge in current page's query parameters
    const currentParams = new URLSearchParams(window.location.search);
    currentParams.forEach((value, key) => {
      // Don't override base URL params
      if (!searchParams.has(key)) {
        searchParams.set(key, value);
      }
    });

    searchParams.set(KnownQueryParams.sessionId, sessionId);
    return this.resolveWsURL("/ws", searchParams);
  }

  /**
   * The WebSocket URL of the terminal.
   */
  async getTerminalWsURL(): Promise<URL> {
    return this.resolveWsURL("/terminal/ws");
  }

  /**
   * The URL of the copilot server.
   *
   * For copilot, strip all query parameters except the auth token.
   * Copilot doesn't understand arbitrary query params, but we still
   * need access_token for cross-origin authentication.
   * `resolveWsURL` is the single source of truth for token attachment.
   */
  async getLSPURL(lsp: "pylsp" | "basedpyright" | "copilot" | "ty" | "pyrefly"): Promise<URL> {
    if (lsp === "copilot") {
      const url = await this.resolveWsURL(`/lsp/${lsp}`);
      const accessToken = url.searchParams.get(KnownQueryParams.accessToken);
      url.search = "";
      if (accessToken) {
        url.searchParams.set(KnownQueryParams.accessToken, accessToken);
      }
      return url;
    }
    return this.resolveWsURL(`/lsp/${lsp}`);
  }

  getAiURL(path: "agent_chat" | "agent_stop" | "agent_events"): URL {
    return this.formatHttpURL(`/api/ai/${path}`);
  }

  getAgentURL(path: "create" | "message" | "stop" | "status" | "list" | "events"): URL {
    return this.formatHttpURL(`/api/agent/${path}`);
  }

  getAgentBaseURL(): string {
    const url = new URL(this.config.url);
    const cleanPath = url.pathname.replace(/\/$/, "");
    return `${url.origin}${cleanPath}/api/agent`;
  }

  /**
   * The URL of the health check endpoint.
   */
  healthURL(): URL {
    return this.formatHttpURL("/health");
  }

  async isHealthy(): Promise<boolean> {
    // Always healthy if a static notebook (no server)
    if (isStaticNotebook()) {
      return true;
    }

    try {
      const headers: Record<string, string> = {};
      const token = await this.resolveAuthToken();
      if (token) {
        headers.Authorization = `Bearer ${token}`;
      }
      const response = await fetch(this.healthURL().toString(), { headers });
      // If there is a redirect, update the URL in the config
      if (response.redirected) {
        Logger.debug(`Runtime redirected to ${response.url}`);
        // strip /health from the URL, using URL parsing to handle query params
        const redirected = new URL(response.url);
        redirected.pathname = redirected.pathname.replace(/\/health$/, "");
        this.config.url = redirected.toString();
      }

      const success = response.ok;
      if (success && this.isSameOrigin) {
        this.setDOMBaseUri(this.config.url);
      }
      return success;
    } catch (error) {
      Logger.error(
        `Failed to check health: ${error instanceof Error ? error.message : "Unknown error"}`,
        { cause: error },
      );
      return false;
    }
  }

  /**
   * Sets the base URI for resolving relative URLs in the document.
   *
   * @param uri - The base URI to set. This should be a valid URL string.
   *
   * @remarks
   * This method modifies the `<base>` element in the document's `<head>`.
   * If a `<base>` element already exists, its `href` attribute is updated.
   * Otherwise, a new `<base>` element is created and appended to the `<head>`.
   *
   * Side effects:
   * - Changes how relative URLs are resolved in the document.
   * - May affect the behavior of scripts, styles, and other resources that use relative URLs.
   */
  private setDOMBaseUri(uri: string) {
    // Remove query params from the URI
    uri = uri.split("?", 1)[0];

    // Make sure there is a trailing slash
    if (!uri.endsWith("/")) {
      uri += "/";
    }

    let base = document.querySelector("base");
    if (base) {
      base.setAttribute("href", uri);
    } else {
      base = document.createElement("base");
      base.setAttribute("href", uri);
      document.head.append(base);
    }
  }

  /**
   * Mark the runtime as already healthy. Called by the embed boot layer
   * which verifies health before creating the RuntimeManager, so the
   * init() retry loop can be skipped entirely.
   */
  markHealthy(): void {
    if (!this.initialHealthyCheck.status === "resolved") {
      Logger.debug("Runtime pre-marked as healthy (boot verified)");
      this.initialHealthyCheck.resolve();
    }
  }

  async init(options?: { disableRetryDelay?: boolean }) {
    // If already resolved (e.g. by markHealthy), skip the retry loop.
    if (this.initialHealthyCheck.status === "resolved") {
      return;
    }

    Logger.debug("Initializing runtime...");
    let retries = 0;
    const maxRetries = 25;
    const baseDelay = 100;
    const growthFactor = 1.2;
    const maxDelay = 2000;

    while (!(await this.isHealthy())) {
      if (retries >= maxRetries) {
        Logger.error(`Failed to connect after ${maxRetries} retries`);
        this.initialHealthyCheck.reject(
          new Error(`Failed to connect after ${maxRetries} retries`),
        );
        return;
      }
      if (!options?.disableRetryDelay) {
        const delay = Math.min(baseDelay * growthFactor ** retries, maxDelay);
        await new Promise((resolve) => setTimeout(resolve, delay));
      }
      retries++;
    }

    Logger.debug("Runtime is healthy");
    this.initialHealthyCheck.resolve();
  }

  /**
   * Wait for the runtime to be healthy.
   */
  async waitForHealthy(): Promise<void> {
    if (this.lazy) {
      return Promise.reject(new Error("Runtime is lazy — init() was never called"));
    }
    return this.initialHealthyCheck.promise;
  }

  async headers(): Promise<KnownHeaders> {
    const token = await this.resolveAuthToken();

    const result: KnownHeaders = {
      "Sp-Session-Id": getSessionId(),
      "Sp-Server-Token": this.config.serverToken ?? "",
      // Needed for widgets that need absolute URLs when embedding in an iframe
      // e.g. mpl.interactive()
      // We don't prefix with `sp` since those get stripped internally
      "x-runtime-url": this.httpURL.toString(),
    };

    if (token) {
      result.Authorization = `Bearer ${token}`;
    }

    return result;
  }

  sessionHeaders(): Pick<KnownHeaders, "Sp-Session-Id"> {
    return {
      "Sp-Session-Id": getSessionId(),
    };
  }
}

interface KnownHeaders {
  "Sp-Session-Id": SessionId;
  "Sp-Server-Token": string;
  "x-runtime-url": string;
  [key: string]: string;
}

function asWsUrl(url: string): URL {
  if (!url.startsWith("http")) {
    Logger.warn(`URL must start with http: ${url}`);
    const newUrl = new URL(url);
    newUrl.protocol = "ws";
    return newUrl;
  }
  // Replace the protocol http with ws
  return new URL(url.replace(/^http/, "ws"));
}
