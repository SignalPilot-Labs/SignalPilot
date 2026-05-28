import { useAtom, useAtomValue, useSetAtom } from "jotai";
import { useRef } from "react";
import { useErrorBoundary } from "react-error-boundary";
import { toast } from "@/components/ui/use-toast";
import { getNotebook, useCellActions } from "@/core/cells/cells";
import { applyTransactionChanges } from "@/core/cells/document-changes";
import { AUTOCOMPLETER } from "@/core/codemirror/completion/Autocompleter";
import type {
  NotificationMessageData,
  NotificationPayload,
} from "@/core/kernel/messages";
import {
  MAX_RETRIES,
  useConnectionTransport,
} from "@/core/websocket/useWebSocket";
import { renderHTML } from "@/plugins/core/RenderHTML";
import {
  handleWidgetMessage,
  MODEL_MANAGER,
} from "@/plugins/impl/anywidget/model";
import { logNever } from "@/utils/assertNever";
import { prettyError } from "@/utils/errors";
import {
  type JsonString,
  safeExtractSetUIElementMessageBuffers,
} from "@/utils/json/base64";
import { jsonParseWithSpecialChar } from "@/utils/json/json-parser";
import { Logger } from "@/utils/Logger";
import { reloadSafe } from "@/utils/reload-safe";
import { useAlertActions } from "../alerts/state";
import { cacheInfoAtom } from "../cache/requests";
import { SCRATCH_CELL_ID } from "../cells/ids";
import { useRunsActions } from "../cells/runs";
import { focusAndScrollCellOutputIntoView } from "../cells/scrollCellIntoView";
import type { CellData } from "../cells/types";
import { capabilitiesAtom } from "../config/capabilities";
import { useSetAppConfig } from "../config/config";
import { useDataSourceActions } from "../datasets/data-source-connections";
import type { ConnectionName } from "../datasets/engines";
import {
  PreviewSQLSchemaList,
  PreviewSQLTable,
  PreviewSQLTableList,
  ValidateSQL,
} from "../datasets/request-registry";
import { useDatasetsActions } from "../datasets/state";
import { UI_ELEMENT_REGISTRY } from "../dom/uiregistry";
import { kernelStartupErrorAtom, useBannersActions } from "../errors/state";
import { FUNCTIONS_REGISTRY } from "../functions/FunctionRegistry";
import {
  handleCellNotificationeration,
  handleKernelReady,
  handleRemoveUIElements,
} from "../kernel/handlers";
import { queryParamHandlers } from "../kernel/queryParamHandlers";
import { getSessionId, regenerateSessionId, type SessionId } from "../kernel/session";
import { isSwitchingNotebookAtom as isSwitchingNotebookAtom_ } from "../notebook-switcher";
import { store } from "../state/jotai";
import { kernelStateAtom } from "../kernel/state";
import { type LayoutState, useLayoutActions } from "../layout/layout";
import { kioskModeAtom } from "../mode";
import { connectionAtom } from "../network/connection";
import type { RequestId } from "../network/DeferredRequestRegistry";
import { useRuntimeManager } from "../runtime/config";
import { SECRETS_REGISTRY } from "../secrets/request-registry";
import { isStaticNotebook } from "../static/static-state";
import { rawFallbackAtom } from "../meta/state";
import {
  DownloadStorage,
  ListStorageEntries,
} from "../storage/request-registry";
import { useStorageActions } from "../storage/state";
import { useVariablesActions } from "../variables/state";
import type { VariableName } from "../variables/types";
import {
  type ConnectionStatus,
  WebSocketClosedReason,
  WebSocketState,
} from "./types";

const SUPPORTS_LAZY_KERNELS = true;

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
      // Empty/undefined reasons are normal transient closes. Anything else is
      // an unknown server reason; warn so a new SP_* reason doesn't fall
      // silently into the retry path.
      if (event.reason) {
        logNever(event.reason as never);
      }
  }
  // partysocket stops retrying silently once `maxRetries` is hit; surface
  // CLOSED so callers can detect the give-up.
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

function getExistingCells(): CellData[] | undefined {
  if (!SUPPORTS_LAZY_KERNELS) {
    return undefined;
  }

  // Remove scratch pad
  return Object.values(getNotebook().cellData).filter(
    (cell) => cell.id !== SCRATCH_CELL_ID,
  );
}

/**
 * Creates a connection to the SignalPilot kernel and handles incoming messages.
 */
export function useSpKernelConnection(opts: {
  sessionId: SessionId;
  autoInstantiate: boolean;
  setCells: (cells: CellData[], layout: LayoutState) => void;
}) {
  // Track whether we want to try reconnecting.
  const shouldTryReconnecting = useRef<boolean>(true);

  const retryCount = useRef(0);
  const TERMINAL_RETRYABLE = new Set([
    "SP_NO_SESSION",
    "SP_NO_SESSION_ID",
    "SP_SHUTDOWN",
    "SP_WRONG_KERNEL_ID",
  ]);
  const MAX_TERMINAL_RETRIES = 2;
  const { autoInstantiate, sessionId: _sessionId, setCells } = opts;
  const { showBoundary } = useErrorBoundary();

  const { handleCellMessage } = useCellActions();
  const actionsWithoutMiddleware = useCellActions({ skipMiddleware: true });

  const handleDocumentTransaction = (
    transaction: NotificationMessageData<"notebook-document-transaction">["transaction"],
  ) => {
    applyTransactionChanges(
      transaction.changes,
      actionsWithoutMiddleware,
      () => getNotebook().cellIds.inOrderIds,
    );
  };
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

  const handleMessage = (e: MessageEvent<JsonString<NotificationPayload>>) => {
    const msg = jsonParseWithSpecialChar(e.data);
    switch (msg.data.op) {
      case "reload":
        reloadSafe();
        return;
      case "kernel-ready": {
        const existingCells = getExistingCells();

        handleKernelReady(msg.data, {
          autoInstantiate,
          setCells,
          setLayoutData,
          setAppConfig,
          setCapabilities,
          setKernelState,
          onError: showBoundary,
          existingCells,
        });
        setKioskMode(msg.data.kiosk);
        // Clear notebook switching state
        store.set(isSwitchingNotebookAtom_, false);
        return;
      }

      case "completed-run":
        return;
      case "interrupted":
        return;

      case "kernel-startup-error":
        // Full error received via message before websocket close
        setKernelStartupError(msg.data.error);
        return;

      case "send-ui-element-message": {
        const uiElement = msg.data.ui_element;
        if (uiElement) {
          const buffers = safeExtractSetUIElementMessageBuffers(msg.data);
          UI_ELEMENT_REGISTRY.broadcastMessage(
            uiElement,
            msg.data.message,
            buffers,
          );
        }
        return;
      }

      case "model-lifecycle":
        handleWidgetMessage(MODEL_MANAGER, msg.data);
        return;

      case "remove-ui-elements":
        handleRemoveUIElements(msg.data);
        return;

      case "completion-result":
        AUTOCOMPLETER.resolve(msg.data.completion_id, msg.data);
        return;
      case "function-call-result":
        FUNCTIONS_REGISTRY.resolve(msg.data.function_call_id, msg.data);
        return;
      case "cell-op": {
        handleCellNotificationeration(msg.data, handleCellMessage);
        const cellData = getNotebook().cellData[msg.data.cell_id];
        if (!cellData) {
          return;
        }
        addCellNotification({
          cellNotification: msg.data,
          code: cellData.code,
        });
        return;
      }

      case "variables":
        setVariables(
          msg.data.variables.map((v) => ({
            name: v.name,
            declaredBy: v.declared_by,
            usedBy: v.used_by,
          })),
        );
        filterDatasetsFromVariables(msg.data.variables.map((v) => v.name));
        filterDataSourcesFromVariables(msg.data.variables.map((v) => v.name));
        filterStorageFromVariables(msg.data.variables.map((v) => v.name));
        return;
      case "variable-values":
        setMetadata(
          msg.data.variables.map((v) => ({
            name: v.name as VariableName,
            dataType: v.datatype,
            value: v.value,
          })),
        );
        return;
      case "alert":
        // Always suppress "Reconnected" alerts — not useful in project context
        if (msg.data.title === "Reconnected") {
          return;
        }
        toast({
          title: msg.data.title,
          description: renderHTML({
            html: msg.data.description,
          }),
          variant: msg.data.variant,
        });
        return;
      case "banner":
        if (msg.data.title === "Reconnected") {
          return;
        }
        addBanner(msg.data);
        return;
      case "missing-package-alert":
        addPackageAlert({
          ...msg.data,
          kind: "missing",
        });
        return;
      case "installing-package-alert":
        addPackageAlert({
          ...msg.data,
          kind: "installing",
        });
        return;
      case "startup-logs":
        addStartupLog({
          content: msg.data.content,
          status: msg.data.status,
        });
        return;
      case "query-params-append":
        queryParamHandlers.append(msg.data);
        return;

      case "query-params-set":
        queryParamHandlers.set(msg.data);
        return;

      case "query-params-delete":
        queryParamHandlers.delete(msg.data);
        return;

      case "query-params-clear":
        queryParamHandlers.clear();
        return;

      case "datasets":
        addDatasets(msg.data);
        return;
      case "data-column-preview":
        addColumnPreview(msg.data);
        return;
      case "sql-table-preview":
        PreviewSQLTable.resolve(msg.data.request_id, msg.data);
        return;
      case "sql-table-list-preview":
        PreviewSQLTableList.resolve(msg.data.request_id, msg.data);
        return;
      case "sql-schema-list-preview":
        PreviewSQLSchemaList.resolve(msg.data.request_id, msg.data);
        return;
      case "validate-sql-result":
        ValidateSQL.resolve(msg.data.request_id as RequestId, msg.data);
        return;
      case "secret-keys-result":
        SECRETS_REGISTRY.resolve(msg.data.request_id, msg.data);
        return;
      case "cache-info":
        setCacheInfo(msg.data);
        return;
      case "cache-cleared":
        // Cache cleared, could refresh cache info if needed
        return;
      case "data-source-connections":
        addDataSourceConnection({
          connections: msg.data.connections.map((conn) => ({
            ...conn,
            name: conn.name as ConnectionName,
          })),
        });
        return;
      case "storage-namespaces":
        setStorageNamespaces(msg.data);
        return;
      case "storage-entries":
        ListStorageEntries.resolve(msg.data.request_id as RequestId, msg.data);
        return;
      case "storage-download-ready":
        DownloadStorage.resolve(msg.data.request_id as RequestId, msg.data);
        return;

      case "reconnected":
        return;

      case "focus-cell":
        focusAndScrollCellOutputIntoView(msg.data.cell_id);
        return;
      case "notebook-document-transaction":
        handleDocumentTransaction(msg.data.transaction);
        return;
      default:
        logNever(msg.data);
    }
  };

  const tryReconnecting = (code?: number, reason?: string) => {
    // If not properly gated, we could try reconnecting forever if the
    // issue is not transient. So we want to try reconnecting only once after an
    // open connection is closed.
    if (shouldTryReconnecting.current) {
      shouldTryReconnecting.current = false;
      ws.reconnect(code, reason);
    }
  };

  // Manual reconnect. Probes /health first to fail fast when the runtime
  // is unreachable, instead of waiting on partysocket's retry budget.
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
    /**
     * Unique URL for this session.
     */
    url: async () => (await runtimeManager.getWsURL(getSessionId())).toString(),

    /**
     * Open callback. Set the connection status to open.
     */
    onOpen: async () => {
      // If we are open, we can reset our reconnecting flag.
      shouldTryReconnecting.current = true;
      retryCount.current = 0;

      // DO NOT COMMIT THIS UNCOMMENTED
      // Uncomment to emulate a slow connection
      // await new Promise((resolve) => setTimeout(resolve, 10_000));

      setConnection({ state: WebSocketState.OPEN });
    },

    /**
     * Wait to connect. Gates on:
     * 1. Runtime health check (pod is up and responding)
     * 2. Project sync completion (files are on the pod)
     * 3. Stale session cleanup (prevents SP_ALREADY_CONNECTED)
     *
     * All downstream connections (terminal, LSP) also wait for the
     * kernel to be OPEN, so this single gate protects everything.
     */
    waitToConnect: async () => {
      if (isStaticNotebook()) {
        return;
      }

      if (!runtimeManager.isSameOrigin) {
        await runtimeManager.waitForHealthy();
      }
    },

    /**
     * Handle messages sent by the kernel.
     */
    onMessage: (e) => {
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

    /**
     * Handle a close event. We may want to reconnect.
     */
    onClose: (e) => {
      Logger.warn("WebSocket closed", e.code, e.reason);
      const decision = classifyCloseEvent(e, {
        retryCount: ws.retryCount,
        maxRetries: MAX_RETRIES,
      });
      if (decision.kind === "terminal" && decision.closeTransport) {
        const reason = e.reason ?? "";

        // Auto-takeover: when the pod says a session is already connected
        // (e.g. stale session from Strict Mode remount, page refresh, or
        // another tab), call /kernel/takeover to reclaim the kernel and retry.
        if (
          reason === "SP_ALREADY_CONNECTED" &&
          retryCount.current < MAX_TERMINAL_RETRIES
        ) {
          retryCount.current += 1;
          setConnection({ state: WebSocketState.CONNECTING });
          const searchParams = new URL(window.location.href).searchParams;
          const takeoverUrl = runtimeManager.formatHttpURL(`/api/kernel/takeover?${searchParams.toString()}`).toString();
          runtimeManager.headers().then((hdrs) =>
            fetch(takeoverUrl, {
              method: "POST",
              headers: { "Content-Type": "application/json", ...hdrs },
              body: "{}",
            })
          ).then(() => {
              regenerateSessionId();
              setTimeout(() => ws.reconnect(), 300);
            })
            .catch(() => {
              regenerateSessionId();
              setTimeout(() => ws.reconnect(), 500);
            });
          return;
        }

        if (
          TERMINAL_RETRYABLE.has(reason) &&
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

    /**
     * When we encounter an error, we should close the connection.
     */
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
