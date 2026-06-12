import type { SetStateAction } from "jotai";
import { type CellActions, getNotebook } from "@/core/cells/cells";
import { applyTransactionChanges } from "@/core/cells/document-changes";
import { AUTOCOMPLETER } from "@/core/codemirror/completion/Autocompleter";
import type {
  Banner,
  Capabilities,
  CellMessage,
  NotificationMessageData,
  NotificationPayload,
} from "@/core/kernel/messages";
import { renderHTML } from "@/plugins/core/RenderHTML";
import {
  handleWidgetMessage,
  MODEL_MANAGER,
} from "@/plugins/impl/anywidget/model";
import { logNever } from "@/utils/assertNever";
import {
  type JsonString,
  safeExtractSetUIElementMessageBuffers,
} from "@/utils/json/base64";
import { jsonParseWithSpecialChar } from "@/utils/json/json-parser";
import { reloadSafe } from "@/utils/reload-safe";
import { toast } from "@/components/ui/use-toast";
import type { MissingPackageAlert, InstallingPackageAlert } from "../alerts/state";
import { SCRATCH_CELL_ID } from "../cells/ids";
import type { CellData } from "../cells/types";
import type { AppConfig } from "../config/config-schema";
import type { ConnectionName } from "../datasets/engines";
import type { DataSourceConnection } from "../datasets/data-source-connections";
import {
  PreviewSQLSchemaList,
  PreviewSQLTable,
  PreviewSQLTableList,
  ValidateSQL,
} from "../datasets/request-registry";
import { UI_ELEMENT_REGISTRY } from "../dom/uiregistry";
import { FUNCTIONS_REGISTRY } from "../functions/FunctionRegistry";
import {
  handleCellNotificationeration,
  handleKernelReady,
  handleRemoveUIElements,
} from "../kernel/handlers";
import { queryParamHandlers } from "../kernel/queryParamHandlers";
import type { KernelState } from "../kernel/state";
import { isSwitchingNotebookAtom as isSwitchingNotebookAtom_ } from "../notebook-switcher";
import { store } from "../state/jotai";
import type { LayoutData, LayoutState } from "../layout/layout";
import type { LayoutType } from "@/components/editor/renderers/types";
import type { RequestId } from "../network/DeferredRequestRegistry";
import { SECRETS_REGISTRY } from "../secrets/request-registry";
import { focusAndScrollCellOutputIntoView } from "../cells/scrollCellIntoView";
import {
  DownloadStorage,
  ListStorageEntries,
} from "../storage/request-registry";
import type { Variable, VariableName } from "../variables/types";

const SUPPORTS_LAZY_KERNELS = true;

function getExistingCells(): CellData[] | undefined {
  if (!SUPPORTS_LAZY_KERNELS) {
    return undefined;
  }
  // When switching notebooks, discard existing cells so the new
  // kernel-ready payload is used instead of stale local cells.
  if (store.get(isSwitchingNotebookAtom_)) {
    console.log("[getExistingCells] switching notebook — returning undefined");
    return undefined;
  }
  const cells = Object.values(getNotebook().cellData).filter(
    (cell) => cell.id !== SCRATCH_CELL_ID,
  );
  console.log("[getExistingCells] returning", cells.length, "existing cells");
  return cells;
}

export interface KernelMessageActions {
  autoInstantiate: boolean;
  setCells: (cells: CellData[], layout: LayoutState) => void;
  handleCellMessage: (msg: CellMessage) => void;
  cellActions: CellActions;
  addCellNotification: (payload: {
    cellNotification: NotificationMessageData<"cell-op">;
    code: string;
  }) => void;
  setKernelState: (state: SetStateAction<KernelState>) => void;
  setAppConfig: (config: AppConfig) => void;
  setVariables: (variables: Variable[]) => void;
  setMetadata: (
    variables: Array<{
      name: VariableName;
      value?: string | null;
      dataType?: string | null;
    }>,
  ) => void;
  addColumnPreview: (data: NotificationMessageData<"data-column-preview">) => void;
  addDatasets: (data: NotificationMessageData<"datasets">) => void;
  filterDatasetsFromVariables: (names: VariableName[]) => void;
  addDataSourceConnection: (data: { connections: DataSourceConnection[] }) => void;
  filterDataSourcesFromVariables: (names: VariableName[]) => void;
  setLayoutData: (payload: { layoutView: LayoutType; data: LayoutData }) => void;
  addBanner: (data: Banner) => void;
  addPackageAlert: (data: MissingPackageAlert | InstallingPackageAlert) => void;
  addStartupLog: (data: { content: string; status: "append" | "start" | "done" }) => void;
  setKioskMode: (mode: boolean) => void;
  setCapabilities: (capabilities: Capabilities) => void;
  setCacheInfo: (data: NotificationMessageData<"cache-info">) => void;
  setKernelStartupError: (error: string) => void;
  setStorageNamespaces: (data: NotificationMessageData<"storage-namespaces">) => void;
  filterStorageFromVariables: (names: VariableName[]) => void;
  showBoundary: (error: Error) => void;
}

export function createMessageHandler(
  actions: KernelMessageActions,
): (e: MessageEvent<JsonString<NotificationPayload>>) => void {
  const handleDocumentTransaction = (
    transaction: NotificationMessageData<"notebook-document-transaction">["transaction"],
  ) => {
    applyTransactionChanges(
      transaction.changes,
      actions.cellActions,
      () => getNotebook().cellIds.inOrderIds,
    );
  };

  return (e: MessageEvent<JsonString<NotificationPayload>>) => {
    const msg = jsonParseWithSpecialChar(e.data);
    switch (msg.data.op) {
      case "reload":
        reloadSafe();
        return;
      case "kernel-ready": {
        console.log("[kernel-ready] received:", msg.data.cell_ids?.length, "cells from server, codes:", msg.data.codes?.map((c: string) => c.slice(0, 30)));
        const existingCells = getExistingCells();
        console.log("[kernel-ready] existingCells:", existingCells?.length ?? "undefined", "resumed:", msg.data.resumed);
        handleKernelReady(msg.data, {
          autoInstantiate: actions.autoInstantiate,
          setCells: actions.setCells,
          setLayoutData: actions.setLayoutData,
          setAppConfig: actions.setAppConfig,
          setCapabilities: actions.setCapabilities,
          setKernelState: actions.setKernelState,
          onError: actions.showBoundary,
          existingCells,
        });
        actions.setKioskMode(msg.data.kiosk);
        store.set(isSwitchingNotebookAtom_, false);
        console.log("[kernel-ready] done, isSwitching reset to false");
        return;
      }

      case "completed-run":
        return;
      case "interrupted":
        return;

      case "kernel-startup-error":
        actions.setKernelStartupError(msg.data.error);
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
        handleCellNotificationeration(msg.data, actions.handleCellMessage);
        const cellData = getNotebook().cellData[msg.data.cell_id];
        if (!cellData) {
          return;
        }
        actions.addCellNotification({
          cellNotification: msg.data,
          code: cellData.code,
        });
        return;
      }

      case "variables":
        actions.setVariables(
          msg.data.variables.map((v) => ({
            name: v.name,
            declaredBy: v.declared_by,
            usedBy: v.used_by,
          })),
        );
        actions.filterDatasetsFromVariables(
          msg.data.variables.map((v) => v.name) as VariableName[],
        );
        actions.filterDataSourcesFromVariables(
          msg.data.variables.map((v) => v.name) as VariableName[],
        );
        actions.filterStorageFromVariables(
          msg.data.variables.map((v) => v.name) as VariableName[],
        );
        return;
      case "variable-values":
        actions.setMetadata(
          msg.data.variables.map((v) => ({
            name: v.name as VariableName,
            dataType: v.datatype,
            value: v.value,
          })),
        );
        return;
      case "alert":
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
        actions.addBanner(msg.data);
        return;
      case "missing-package-alert":
        actions.addPackageAlert({
          ...msg.data,
          kind: "missing",
        });
        return;
      case "installing-package-alert":
        actions.addPackageAlert({
          ...msg.data,
          kind: "installing",
        });
        return;
      case "startup-logs":
        actions.addStartupLog({
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
        actions.addDatasets(msg.data);
        return;
      case "data-column-preview":
        actions.addColumnPreview(msg.data);
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
        actions.setCacheInfo(msg.data);
        return;
      case "cache-cleared":
        return;
      case "data-source-connections":
        actions.addDataSourceConnection({
          connections: msg.data.connections.map((conn) => ({
            ...conn,
            name: conn.name as ConnectionName,
          })) as DataSourceConnection[],
        });
        return;
      case "storage-namespaces":
        actions.setStorageNamespaces(msg.data);
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
}
