import ReconnectingWebSocket, { type UrlProvider } from "partysocket/ws";
import { useEffect, useRef } from "react";
import { Logger } from "@/utils/Logger";
import { BasicTransport } from "./transports/basic";
import type { IConnectionTransport } from "./transports/transport";

interface UseConnectionTransportOptions {
  /**
   * Async factory that resolves the WebSocket URL. Called per connection
   * attempt by ReconnectingWebSocket.
   */
  url: () => string | Promise<string>;
  /**
   * Async factory that resolves the subprotocols to offer.
   * Awaited once (alongside `url`) when the socket first opens.
   * The resolved array is forwarded to the ReconnectingWebSocket
   * constructor (second argument) so auth is carried via
   * Sec-WebSocket-Protocol — never via a query param.
   *
   * Implementation note: partysocket/ws protocols are set once at
   * construction time. We pre-resolve via a wrapping URL factory so
   * that the first connection attempt captures the current token.
   * Token rotation causes a full reconnect cycle which re-creates the
   * socket via the useEffect dependency, picking up fresh protocols.
   */
  protocols?: () => Promise<string[]>;
  static: boolean;
  waitToConnect: () => Promise<void>;
  onOpen: (event: WebSocketEventMap["open"]) => void;
  onMessage: (event: WebSocketEventMap["message"]) => void;
  onClose: (event: WebSocketEventMap["close"]) => void;
  onError: (event: WebSocketEventMap["error"]) => void;
}

export const MAX_RETRIES = 10;

function createConnectionTransport(
  options: Pick<UseConnectionTransportOptions, "url" | "protocols" | "static">,
): IConnectionTransport {
  if (options.static) {
    return BasicTransport.empty();
  }

  const { url: urlFactory, protocols: protocolsFactory } = options;

  if (!protocolsFactory) {
    // No auth subprotocols needed — plain socket.
    return new ReconnectingWebSocket(urlFactory as UrlProvider, undefined, {
      maxRetries: MAX_RETRIES,
      debug: false,
      startClosed: true,
      connectionTimeout: 10_000,
    }) as unknown as IConnectionTransport;
  }

  // Auth is conveyed via Sec-WebSocket-Protocol (two-token form).
  //
  // partysocket/ws accepts `protocols` as `string | string[] | undefined` at
  // construction time (not a factory). We work around this by:
  // 1. Wrapping the URL factory to co-resolve protocols on every connection
  //    attempt and stash them in `latestProtocols`.
  // 2. Passing a Proxy array whose reads are forwarded to `latestProtocols`.
  //    partysocket reads the protocols array when it calls
  //    `new WebSocket(url, protocols)` — which happens AFTER the async URL
  //    factory resolves — so latestProtocols is already populated.
  let latestProtocols: string[] = [];

  const wrappedUrlFactory = async (): Promise<string> => {
    // Resolve URL and protocols in parallel; fail-fast on either error.
    const [resolvedUrl, resolvedProtocols] = await Promise.all([
      urlFactory(),
      protocolsFactory(),
    ]);
    latestProtocols = resolvedProtocols;
    return resolvedUrl;
  };

  // Proxy array forwards reads to `latestProtocols` so partysocket always
  // sees the value that was captured by the most recent URL-factory call.
  const protocolsProxy = new Proxy([] as string[], {
    get(_target, prop, _receiver) {
      return Reflect.get(latestProtocols, prop, latestProtocols);
    },
  });

  return new ReconnectingWebSocket(
    wrappedUrlFactory as UrlProvider,
    protocolsProxy as string[],
    {
      maxRetries: MAX_RETRIES,
      debug: false,
      startClosed: true,
      connectionTimeout: 10_000,
    },
  ) as unknown as IConnectionTransport;
}

export function useConnectionTransport(options: UseConnectionTransportOptions) {
  const { onOpen, onMessage, onClose, onError, waitToConnect } = options;

  const transportRef = useRef<IConnectionTransport>(
    createConnectionTransport(options),
  );

  useEffect(() => {
    let cancelled = false;

    const socket = createConnectionTransport(options);
    transportRef.current = socket;

    socket.addEventListener("open", onOpen);
    socket.addEventListener("close", onClose);
    socket.addEventListener("error", onError);
    socket.addEventListener("message", onMessage);

    if (socket.readyState === WebSocket.CLOSED) {
      void waitToConnect()
        .then(() => {
          if (!cancelled) {
            socket.reconnect();
          }
        })
        .catch((error) => {
          Logger.error("Healthy connection never made", error);
          if (!cancelled) {
            socket.close();
          }
        });
    }

    return () => {
      cancelled = true;
      socket.removeEventListener("open", onOpen);
      socket.removeEventListener("close", onClose);
      socket.removeEventListener("error", onError);
      socket.removeEventListener("message", onMessage);
      socket.close();
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  return transportRef.current;
}
