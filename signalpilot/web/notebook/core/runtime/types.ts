/**
 * An auth token value or a thunk that returns one.
 *
 * Called before every authenticated REST request and before every
 * (re)opened WebSocket / SSE connection. The host application owns
 * token caching and refresh — we call the thunk on each invocation
 * with no internal cache.
 *
 * Do not return `null` or `undefined`. Return `""` if you have no
 * token; the request will be sent without an `Authorization` header
 * (the gateway will 401 on protected routes).
 */
export type AuthTokenProvider = string | (() => string | Promise<string>);

export interface RuntimeConfig {
  /**
   * The URL of the runtime server.
   */
  url: string;
  /**
   * If true, the runtime will not be loaded until the user interacts with the notebook.
   * If false, the runtime will be loaded immediately.
   */
  readonly lazy: boolean;
  /**
   * The server token for the runtime (Skew protection token)
   */
  readonly serverToken?: string;
  /**
   * The API key or JWT token for the remote backend (used for authentication).
   * Accepts a static string or a thunk — see {@link AuthTokenProvider}.
   */
  readonly authToken?: AuthTokenProvider | null;
  /**
   * If true, skip the health check retry loop — the caller already
   * verified the runtime is reachable (e.g. NotebookBoot's pre-check).
   */
  readonly healthVerified?: boolean;
}
