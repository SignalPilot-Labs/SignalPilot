import { WebSocketTransport } from "@open-rpc/client-js";
import type { JSONRPCRequestData } from "@open-rpc/client-js/build/Request";
import { Transport } from "@open-rpc/client-js/build/transports/Transport";
import { Logger } from "@/utils/Logger";

export interface ReconnectingWebSocketTransportOptions {
  /**
   * Function that returns the WebSocket URL to connect to.
   * May be async (e.g. requires resolving an auth token).
   */
  getWsUrl: () => string | Promise<string>;

  /**
   * Optional function that returns the subprotocols to offer on the WebSocket.
   * Used to carry auth via Sec-WebSocket-Protocol (two-token form:
   * ["signalpilot.auth", "<token>"]) instead of a query param.
   * When provided, the returned array is forwarded to `new WebSocket(url, protocols)`.
   *
   * `@open-rpc/client-js` v1.8.x `WebSocketTransport` does not expose a
   * `webSocketFactory` hook. We intercept via a thin subclass
   * (`SubprotocolWebSocketTransport`) that overrides `connect()` to attach
   * subprotocols before the parent wires up event handlers.
   * May be async (e.g. requires resolving an auth token alongside the URL).
   */
  getSubprotocols?: () => string[] | Promise<string[]>;

  /**
   * Optional function to wait for before attempting to connect.
   * This is useful for ensuring dependencies (like the runtime) are ready.
   */
  waitForConnection?: () => Promise<void>;

  /**
   * Optional callback that is called after a successful reconnection.
   * This allows the LSP client to re-synchronize state (e.g., re-send document open notifications).
   */
  onReconnect?: () => Promise<void>;
}

interface Subscription {
  event: "pending" | "notification" | "response" | "error";
  handler: Parameters<Transport["subscribe"]>[1];
}

/**
 * WebSocket transport that sends auth via Sec-WebSocket-Protocol subprotocols.
 *
 * `@open-rpc/client-js` v1.8.x `WebSocketTransport` does not expose a
 * `webSocketFactory` hook — its `connect()` always calls `new WebSocket(url)`
 * without protocols. We work around this by:
 *
 *   1. Capturing the URL and subprotocols at construction time.
 *   2. Overriding `connect()` to first assign `this.connection` to a native
 *      `new WebSocket(url, subprotocols)`, then calling `super.connect()`.
 *      The parent's `connect()` reads `this.connection` first if it exists
 *      (implementation-dependent), OR it overwrites it. To be safe we
 *      patch the parent's `connect()` by replacing the global WebSocket
 *      constructor for the duration of the parent call.
 *
 * If a future version of `@open-rpc/client-js` exposes a factory hook,
 * delete this class and use that instead.
 */
class SubprotocolWebSocketTransport extends WebSocketTransport {
  private readonly wsUrl: string;
  private readonly subprotocols: string[];

  constructor(url: string, subprotocols: string[]) {
    super(url);
    this.wsUrl = url;
    this.subprotocols = subprotocols;
  }

  override connect(): Promise<void> {
    const { wsUrl, subprotocols } = this;
    if (subprotocols.length === 0) {
      return super.connect();
    }

    // Temporarily replace the global WebSocket constructor so that
    // the parent's `new WebSocket(url)` call creates a subprotocol-carrying
    // socket. We restore it in a finally block.
    //
    // This is the only reliable hook point when the library doesn't expose a
    // factory. The window of replacement is synchronous (microtask-safe):
    // the parent creates the WS object in the synchronous part of connect()
    // before any async handshake completes.
    const OriginalWebSocket = globalThis.WebSocket;
    try {
      globalThis.WebSocket = class extends OriginalWebSocket {
        // eslint-disable-next-line @typescript-eslint/no-useless-constructor
        constructor(url: string | URL, protocols?: string | string[]) {
          // The library passes no protocols; inject the subprotocols from
          // the outer closure. If for any reason protocols is non-empty,
          // that means the library was updated to pass them — prefer those.
          super(url, protocols !== undefined && protocols !== "" ? protocols : subprotocols);
        }
      } as unknown as typeof WebSocket;
      return super.connect();
    } finally {
      // Restore immediately — the parent's connect() creates the WS
      // synchronously; any awaits are for the socket open event.
      globalThis.WebSocket = OriginalWebSocket;
    }
  }
}

/**
 * A WebSocket transport that automatically reconnects when the connection is lost.
 * This handles cases like computer sleep/wake or network interruptions.
 */
export class ReconnectingWebSocketTransport extends Transport {
  private delegate: WebSocketTransport | undefined;
  private readonly options: ReconnectingWebSocketTransportOptions;
  private connectionPromise: Promise<void> | undefined;
  private isClosed = false;
  private hasConnectedBefore = false;
  private pendingSubscriptions: Subscription[] = [];

  constructor(options: ReconnectingWebSocketTransportOptions) {
    super();
    this.options = options;
    this.delegate = undefined;
  }

  /**
   * Create a new WebSocket delegate, replacing any existing one.
   * Async to support token resolution for URL and subprotocols.
   */
  private async createDelegate(): Promise<WebSocketTransport> {
    // Close the old delegate if it exists
    if (this.delegate) {
      try {
        this.delegate.close();
      } catch (error) {
        Logger.warn("Error closing old WebSocket delegate", error);
      }
    }

    // Resolve URL and subprotocols in parallel for efficiency.
    const [url, subprotocols] = await Promise.all([
      this.options.getWsUrl(),
      this.options.getSubprotocols?.() ?? [],
    ]);

    // Use a subprotocol-aware delegate when auth subprotocols are present.
    // Auth is carried via Sec-WebSocket-Protocol (two-token form) — never
    // via query param. The gateway rejects ?access_token= in cloud mode.
    this.delegate =
      subprotocols.length > 0
        ? new SubprotocolWebSocketTransport(url, subprotocols)
        : new WebSocketTransport(url);

    // Re-register all pending subscriptions on the new delegate
    for (const { event, handler } of this.pendingSubscriptions) {
      this.delegate.subscribe(event, handler);
    }

    return this.delegate;
  }

  /**
   * Check if the current delegate's WebSocket is in a closed or closing state.
   */
  private isDelegateClosedOrClosing(): boolean {
    if (!this.delegate) {
      return true;
    }

    // Access the internal connection to check its readyState
    const ws = this.delegate.connection;
    if (!ws) {
      return true;
    }

    // WebSocket.CLOSING = 2, WebSocket.CLOSED = 3
    return (
      ws.readyState === WebSocket.CLOSING || ws.readyState === WebSocket.CLOSED
    );
  }

  override async connect() {
    // Don't reconnect if explicitly closed
    if (this.isClosed) {
      throw new Error("Transport is closed");
    }

    // If already connecting, wait for that connection
    if (this.connectionPromise) {
      return this.connectionPromise;
    }

    this.connectionPromise = (async () => {
      try {
        // Wait for dependencies to be ready (e.g., runtime connection)
        if (this.options.waitForConnection) {
          await this.options.waitForConnection();
        }

        // Create a new delegate if needed
        let delegate = this.delegate;
        if (!delegate || this.isDelegateClosedOrClosing()) {
          delegate = await this.createDelegate();
        }

        // Connect the delegate
        await delegate.connect();
        Logger.log("WebSocket transport connected successfully");

        // If this is a reconnection, call the onReconnect callback
        const isReconnection = this.hasConnectedBefore;
        this.hasConnectedBefore = true;

        if (isReconnection && this.options.onReconnect) {
          Logger.log("Calling onReconnect callback to re-synchronize state");
          await this.options.onReconnect();
        }
      } catch (error) {
        Logger.error("WebSocket transport connection failed", error);
        // Clear the delegate on failure so we create a new one on retry
        this.delegate = undefined;
        throw error;
      } finally {
        this.connectionPromise = undefined;
      }
    })();

    return this.connectionPromise;
  }

  override close() {
    this.isClosed = true;
    this.delegate?.close();
    this.delegate = undefined;
    this.connectionPromise = undefined;
  }

  override subscribe(...args: Parameters<Transport["subscribe"]>): void {
    // Register handler on parent Transport
    super.subscribe(...args);

    const [event, handler] = args;

    // Track the subscription
    this.pendingSubscriptions.push({ event, handler });

    // Also register on delegate if it exists
    if (this.delegate) {
      this.delegate.subscribe(event, handler);
    }
  }

  override unsubscribe(
    ...args: Parameters<Transport["unsubscribe"]>
  ): import("events").EventEmitter | undefined {
    // Unregister from parent
    const result = super.unsubscribe(...args);

    const [event, handler] = args;

    // Remove from pending subscriptions
    this.pendingSubscriptions = this.pendingSubscriptions.filter(
      (sub) => !(sub.event === event && sub.handler === handler),
    );

    // Also unregister from delegate if it exists
    if (this.delegate) {
      this.delegate.unsubscribe(event, handler);
    }

    return result;
  }

  override async sendData(
    data: JSONRPCRequestData,
    timeout: number | null | undefined,
  ) {
    // If the delegate is closed or closing, try to reconnect
    if (this.isDelegateClosedOrClosing()) {
      Logger.warn("WebSocket is closed or closing, attempting to reconnect");
      try {
        await this.connect();
      } catch (error) {
        Logger.error("Failed to reconnect WebSocket", error);
        throw error;
      }
    }

    // Send the data using the delegate
    return this.delegate?.sendData(data, timeout);
  }
}
