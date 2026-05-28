import ReconnectingWebSocket, { type UrlProvider } from "partysocket/ws";
import { useEffect, useRef } from "react";
import { Logger } from "@/utils/Logger";
import { BasicTransport } from "./transports/basic";
import type { IConnectionTransport } from "./transports/transport";

interface UseConnectionTransportOptions {
  url: () => string | Promise<string>;
  static: boolean;
  waitToConnect: () => Promise<void>;
  onOpen: (event: WebSocketEventMap["open"]) => void;
  onMessage: (event: WebSocketEventMap["message"]) => void;
  onClose: (event: WebSocketEventMap["close"]) => void;
  onError: (event: WebSocketEventMap["error"]) => void;
}

export const MAX_RETRIES = 10;

function createConnectionTransport(
  options: Pick<UseConnectionTransportOptions, "url" | "static">,
): IConnectionTransport {
  if (options.static) {
    return BasicTransport.empty();
  }
  const urlProvider = options.url;
  return new ReconnectingWebSocket(urlProvider as UrlProvider, undefined, {
    maxRetries: MAX_RETRIES,
    debug: false,
    startClosed: true,
    connectionTimeout: 10_000,
  }) as unknown as IConnectionTransport;
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
