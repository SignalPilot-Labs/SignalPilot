import { logNever } from "@/utils/assertNever";
import { type ConnectionStatus, WebSocketClosedReason, WebSocketState } from "./types";

export type CloseDecision =
  | { kind: "terminal"; status: ConnectionStatus; closeTransport: boolean }
  | { kind: "gave-up"; status: ConnectionStatus }
  | { kind: "retry"; status: ConnectionStatus };

export function classifyCloseEvent(
  event: { reason?: string },
  context: { retryCount: number; maxRetries: number },
): CloseDecision {
  switch (event.reason) {
    case "SP_ALREADY_CONNECTED":
      return {
        kind: "terminal",
        status: {
          state: WebSocketState.CLOSED,
          code: WebSocketClosedReason.ALREADY_RUNNING,
          reason: "another browser tab is already connected to the kernel",
          canTakeover: true,
        },
        closeTransport: true,
      };
    case "SP_WRONG_KERNEL_ID":
    case "SP_NO_FILE_KEY":
    case "SP_NO_SESSION_ID":
    case "SP_NO_SESSION":
    case "SP_SHUTDOWN":
      return {
        kind: "terminal",
        status: {
          state: WebSocketState.CLOSED,
          code: WebSocketClosedReason.KERNEL_DISCONNECTED,
          reason: "kernel not found",
        },
        closeTransport: true,
      };
    case "SP_MALFORMED_QUERY":
      return {
        kind: "terminal",
        status: {
          state: WebSocketState.CLOSED,
          code: WebSocketClosedReason.MALFORMED_QUERY,
          reason:
            "the kernel did not recognize a request; please file a bug with SignalPilot",
        },
        closeTransport: false,
      };
    case "SP_KERNEL_STARTUP_ERROR":
      return {
        kind: "terminal",
        status: {
          state: WebSocketState.CLOSED,
          code: WebSocketClosedReason.KERNEL_STARTUP_ERROR,
          reason: "Failed to start kernel sandbox",
        },
        closeTransport: true,
      };
    default:
      if (event.reason) {
        logNever(event.reason as never);
      }
  }

  if (context.retryCount >= context.maxRetries) {
    return {
      kind: "gave-up",
      status: {
        state: WebSocketState.CLOSED,
        code: WebSocketClosedReason.KERNEL_DISCONNECTED,
        reason: "kernel not found",
      },
    };
  }
  return {
    kind: "retry",
    status: { state: WebSocketState.CONNECTING },
  };
}

export const TERMINAL_RETRYABLE_REASONS = new Set([
  "SP_NO_SESSION",
  "SP_NO_SESSION_ID",
  "SP_SHUTDOWN",
  "SP_WRONG_KERNEL_ID",
]);

export const MAX_TERMINAL_RETRIES = 2;
