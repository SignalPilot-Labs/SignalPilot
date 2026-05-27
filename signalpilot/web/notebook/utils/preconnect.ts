const preconnectedOrigins = new Set<string>();

function getKernelWsOrigin(): string | null {
  const protocol = window.location.protocol;
  if (protocol === "https:") return `wss://${window.location.host}`;
  if (protocol === "http:") return `ws://${window.location.host}`;
  return null;
}

/**
 * Inject a `<link rel="preconnect" crossorigin>` for the kernel WebSocket
 * origin so the TCP (+TLS) handshake is warmed up before the user clicks a
 * notebook link.
 *
 * Idempotent: only one link per origin is ever injected.
 * Returns early when the page protocol is not http(s).
 */
export function preconnectKernel(): void {
  const origin = getKernelWsOrigin();
  if (origin === null) {
    return;
  }

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
