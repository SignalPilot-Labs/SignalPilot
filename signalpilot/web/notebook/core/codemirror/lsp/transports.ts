import { ReconnectingWebSocketTransport } from "@/core/lsp/transport";
import { waitForConnectionOpen } from "../../network/connection";
import { getRuntimeManager } from "../../runtime/config";

/**
 * Create a transport for a given LSP server.
 *
 * This ensures we are connected to the SignalPilot runtime
 * before connecting to the LSP server.
 *
 * @param serverName - The name of the LSP server.
 * @param onReconnect - Optional callback to call after reconnection (e.g., to resync documents).
 * @returns The transport.
 */
export function createTransport(
  serverName: "pylsp" | "basedpyright" | "copilot" | "ty" | "pyrefly",
  onReconnect?: () => Promise<void>,
) {
  const runtimeManager = getRuntimeManager();

  // Both getWsUrl and getSubprotocols must share a single getLSPURL() call
  // per connection attempt so the URL and subprotocols are consistent (same
  // token). We cache the in-flight promise and clear it after settlement so
  // the next delegate creation (reconnect) picks up fresh values.
  let pendingResolution: Promise<{ url: URL; subprotocols: string[] }> | null =
    null;

  const resolveOnce = (): Promise<{ url: URL; subprotocols: string[] }> => {
    if (!pendingResolution) {
      pendingResolution = runtimeManager.getLSPURL(serverName).finally(() => {
        // Clear in the next microtask so both same-call consumers see the
        // same promise, but the following delegate creation gets fresh data.
        void Promise.resolve().then(() => {
          pendingResolution = null;
        });
      });
    }
    return pendingResolution;
  };

  return new ReconnectingWebSocketTransport({
    // Auth is conveyed via Sec-WebSocket-Protocol — never via query param.
    // The gateway rejects ?access_token= in cloud mode.
    getWsUrl: async () => {
      const { url } = await resolveOnce();
      return url.toString();
    },
    getSubprotocols: async () => {
      const { subprotocols } = await resolveOnce();
      return subprotocols;
    },
    waitForConnection: async () => {
      await waitForConnectionOpen();
    },
    onReconnect,
  });
}
