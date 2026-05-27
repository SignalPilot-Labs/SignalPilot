/**
 * Derives the WebSocket origin (scheme + host) from the current page location.
 *
 * Returns null when the page protocol is neither http: nor https: (e.g.
 * file:// or chrome-extension://) so callers can bail out safely.
 */
export function buildKernelWsOrigin(): string | null {
  const protocol = window.location.protocol;
  if (protocol === "https:") {
    return `wss://${window.location.host}`;
  }
  if (protocol === "http:") {
    return `ws://${window.location.host}`;
  }
  // Unknown protocol — e.g. file://, chrome-extension://, etc.
  return null;
}

/**
 * Builds a full WebSocket URL for the given path relative to the current
 * page origin.
 *
 * Returns null when the current page protocol is not http: or https:.
 */
export function buildKernelWsUrl(path: string): string | null {
  const origin = buildKernelWsOrigin();
  if (origin === null) {
    return null;
  }
  const normalizedPath = path.startsWith("/") ? path : `/${path}`;
  return `${origin}${normalizedPath}`;
}
