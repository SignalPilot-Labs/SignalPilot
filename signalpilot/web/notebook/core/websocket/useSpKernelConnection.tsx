import { useAtom, useAtomValue, useSetAtom } from "jotai";
import { useRef } from "react";
import { useErrorBoundary } from "react-error-boundary";
import { toast } from "@/components/ui/use-toast";
import { useCellActions } from "@/core/cells/cells";
import type { NotificationPayload } from "@/core/kernel/messages";
import {
  MAX_RETRIES,
  useConnectionTransport,
} from "@/core/websocket/useWebSocket";
import { prettyError } from "@/utils/errors";
import type { JsonString } from "@/utils/json/base64";
import { Logger } from "@/utils/Logger";
import { useAlertActions } from "../alerts/state";
import { cacheInfoAtom } from "../cache/requests";
import { useRunsActions } from "../cells/runs";
import { capabilitiesAtom } from "../config/capabilities";
import { useSetAppConfig } from "../config/config";
import { useDataSourceActions } from "../datasets/data-source-connections";
import { useDatasetsActions } from "../datasets/state";
import { kernelStartupErrorAtom, useBannersActions } from "../errors/state";
import { getSessionId, regenerateSessionId, type SessionId } from "../kernel/session";
import { kernelStateAtom } from "../kernel/state";
import { takeoverKernel } from "../kernel/takeover";
import { type LayoutState, useLayoutActions } from "../layout/layout";
import { kioskModeAtom } from "../mode";
import { connectionAtom } from "../network/connection";
import { useRuntimeManager } from "../runtime/config";
import { isStaticNotebook } from "../static/static-state";
import { rawFallbackAtom } from "../meta/state";
import { useStorageActions } from "../storage/state";
import { useVariablesActions } from "../variables/state";
import {
  type ConnectionStatus,
  WebSocketClosedReason,
  WebSocketState,
} from "./types";
import type { CellData } from "../cells/types";
import {
  classifyCloseEvent,
  TERMINAL_RETRYABLE_REASONS,
  MAX_TERMINAL_RETRIES,
} from "./close-classifier";
import { createMessageHandler, type KernelMessageActions } from "./kernel-message-dispatch";

export type { CloseDecision } from "./close-classifier";
export { classifyCloseEvent } from "./close-classifier";

/**
 * Creates a connection to the kernel and handles incoming messages.
 */
export function useSpKernelConnection(opts: {
  sessionId: SessionId;
  autoInstantiate: boolean;
  setCells: (cells: CellData[], layout: LayoutState) => void;
}) {
  const shouldTryReconnecting = useRef<boolean>(true);
  const retryCount = useRef(0);
  const { autoInstantiate, sessionId: _sessionId, setCells } = opts;
  const { showBoundary } = useErrorBoundary();

  const { handleCellMessage } = useCellActions();
  const actionsWithoutMiddleware = useCellActions({ skipMiddleware: true });
  const { addCellNotification } = useRunsActions();
  const setKernelState = useSetAtom(kernelStateAtom);
  const setAppConfig = useSetAppConfig();
  const { setVariables, setMetadata } = useVariablesActions();
  const { addColumnPreview } = useDatasetsActions();
  const { addDatasets, filterDatasetsFromVariables } = useDatasetsActions();
  const { addDataSourceConnection, filterDataSourcesFromVariables } =
    useDataSourceActions();
  const { setLayoutData } = useLayoutActions();
  const [connection, setConnection] = useAtom(connectionAtom);
  const { addBanner } = useBannersActions();
  const { addPackageAlert, addStartupLog } = useAlertActions();
  const setKioskMode = useSetAtom(kioskModeAtom);
  const setCapabilities = useSetAtom(capabilitiesAtom);
  const runtimeManager = useRuntimeManager();
  const setCacheInfo = useSetAtom(cacheInfoAtom);
  const setKernelStartupError = useSetAtom(kernelStartupErrorAtom);
  const {
    setNamespaces: setStorageNamespaces,
    filterFromVariables: filterStorageFromVariables,
  } = useStorageActions();

  const actions: KernelMessageActions = {
    autoInstantiate,
    setCells,
    handleCellMessage,
    handleCellMessageWithoutMiddleware: actionsWithoutMiddleware.handleCellMessage,
    addCellNotification,
    setKernelState,
    setAppConfig,
    setVariables,
    setMetadata,
    addColumnPreview,
    addDatasets,
    filterDatasetsFromVariables,
    addDataSourceConnection,
    filterDataSourcesFromVariables,
    setLayoutData,
    addBanner,
    addPackageAlert,
    addStartupLog,
    setKioskMode,
    setCapabilities,
    setCacheInfo,
    setKernelStartupError,
    setStorageNamespaces,
    filterStorageFromVariables,
    showBoundary,
  };

  const handleMessage = createMessageHandler(actions);

  const tryReconnecting = (code?: number, reason?: string) => {
    if (shouldTryReconnecting.current) {
      shouldTryReconnecting.current = false;
      ws.reconnect(code, reason);
    }
  };

  const reconnect = async () => {
    if (
      ws.readyState === WebSocket.OPEN ||
      ws.readyState === WebSocket.CONNECTING
    ) {
      return;
    }
    shouldTryReconnecting.current = true;
    setConnection({ state: WebSocketState.CONNECTING });
    const healthy = await runtimeManager.isHealthy();
    if (!healthy) {
      shouldTryReconnecting.current = false;
      setConnection({
        state: WebSocketState.CLOSED,
        code: WebSocketClosedReason.KERNEL_DISCONNECTED,
        reason: "kernel not found",
      });
      return;
    }
    ws.reconnect();
  };

  const isRawFallback = useAtomValue(rawFallbackAtom);

  const ws = useConnectionTransport({
    static: isStaticNotebook() || isRawFallback,

    url: async () => (await runtimeManager.getWsURL(getSessionId())).toString(),

    onOpen: async () => {
      shouldTryReconnecting.current = true;
      retryCount.current = 0;
      setConnection({ state: WebSocketState.OPEN });
    },

    waitToConnect: async () => {
      if (isStaticNotebook()) {
        return;
      }
      if (!runtimeManager.isSameOrigin) {
        await runtimeManager.waitForHealthy();
      }
    },

    onMessage: (e: MessageEvent<JsonString<NotificationPayload>>) => {
      try {
        handleMessage(e);
      } catch (error) {
        Logger.error("Failed to handle message", e.data, error);
        toast({
          title: "Failed to handle message",
          description: prettyError(error),
          variant: "danger",
        });
      }
    },

    onClose: (e) => {
      Logger.warn("WebSocket closed", e.code, e.reason);
      const decision = classifyCloseEvent(e, {
        retryCount: ws.retryCount,
        maxRetries: MAX_RETRIES,
      });
      if (decision.kind === "terminal" && decision.closeTransport) {
        const reason = e.reason ?? "";

        if (
          reason === "SP_ALREADY_CONNECTED" &&
          retryCount.current < MAX_TERMINAL_RETRIES
        ) {
          retryCount.current += 1;
          setConnection({ state: WebSocketState.CONNECTING });
          runtimeManager.headers().then((hdrs) =>
            takeoverKernel(runtimeManager.httpURL.toString().replace(/\/$/, ""), hdrs),
          ).then(() => {
            regenerateSessionId();
            setTimeout(() => ws.reconnect(), 300);
          }).catch((err) => {
            Logger.warn("Takeover failed, retrying with new session:", err);
            regenerateSessionId();
            setTimeout(() => ws.reconnect(), 500);
          });
          return;
        }

        if (
          TERMINAL_RETRYABLE_REASONS.has(reason) &&
          retryCount.current < MAX_TERMINAL_RETRIES
        ) {
          retryCount.current += 1;
          setConnection({ state: WebSocketState.CONNECTING });
          regenerateSessionId();
          setTimeout(() => ws.reconnect(), 500);
          return;
        }
        setConnection(decision.status);
        ws.close();
        return;
      }
      setConnection(decision.status);
      if (decision.kind === "retry") {
        tryReconnecting(e.code, e.reason);
      }
    },

    onError: (e) => {
      Logger.warn("WebSocket error", e);
      setConnection({
        state: WebSocketState.CLOSED,
        code: WebSocketClosedReason.KERNEL_DISCONNECTED,
        reason: "kernel not found",
      });
      tryReconnecting();
    },
  });

  const forceReconnect = () => {
    shouldTryReconnecting.current = false;
    retryCount.current = 0;
    setConnection({ state: WebSocketState.CONNECTING });
    ws.close();
    setTimeout(() => {
      shouldTryReconnecting.current = true;
      regenerateSessionId();
      ws.reconnect();
    }, 500);
  };

  return { connection, reconnect, forceReconnect };
}
