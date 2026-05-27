import { buildKernelWsOrigin } from "@/core/websocket/url";

/**
 * Set of origins for which a <link rel="preconnect"> has already been injected.
 * Keeps the function idempotent across multiple calls.
 */
const preconnectedOrigins = new Set<string>();

/**
 * Inject a `<link rel="preconnect" crossorigin>` for the kernel WebSocket
 * origin so the TCP (+TLS) handshake is warmed up before the user clicks a
 * notebook link.
 *
 * - Dependency-free w.r.t. React — safe to call during render or event handlers.
 * - Idempotent: only one link per origin is ever injected.
 * - Returns early when the page protocol is not http(s): (e.g. file://).
 */
export function preconnectKernel(): void {
  const origin = buildKernelWsOrigin();
  if (origin === null) {
    return;
  }

  // Derive the HTTP(S) origin from the WS(S) origin for the preconnect hint.
  // Browsers accept wss:// in preconnect but the HTTP counterpart is more
  // universally supported — use the same host with the http(s) scheme.
  const httpOrigin = origin.replace(/^wss:\/\//, "https://").replace(/^ws:\/\//, "http://");

  if (preconnectedOrigins.has(httpOrigin)) {
    return;
  }

  preconnectedOrigins.add(httpOrigin);

  const link = document.createElement("link");
  link.rel = "preconnect";
  link.href = httpOrigin;
  link.crossOrigin = "anonymous";
  document.head.appendChild(link);
}
