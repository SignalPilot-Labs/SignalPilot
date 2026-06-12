import { NoKernelConnectedError } from "@/utils/errors";
import { Logger } from "@/utils/Logger";
import { Objects } from "@/utils/objects";
import { memoizeLastValue } from "@/utils/once";
import { waitForKernelToBeInstantiated } from "../kernel/state";
import type { RuntimeManager } from "../runtime/runtime";
import { store } from "../state/jotai";
import { WebSocketState } from "../websocket/types";
import { connectionAtom, waitForConnectionOpen } from "./connection";
import type { EditRequests, RunRequests } from "./types";

type AllRequests = EditRequests & RunRequests;

// We have various requests that act differently when called and not connected to a Kernel:
//
// - throwError: Throws NoKernelConnectedError, caught by requests-toasting.tsx
//   and shown as a toast with a "Connect" button. Use for operations that
//   shouldn't silently fail but also shouldn't auto-start the kernel.
//
// - dropRequest: Silently returns undefined. Only for requests where failure is
//   expected and doesn't matter (e.g., background polling).
//
// - startConnection: Initializes the runtime and waits for connection before
//   executing. Use for user-initiated actions that should "just work" and
//   kick off the kernel if needed (e.g., clicking Run).
//
// - waitForConnectionOpen: Waits for an existing connection but won't start one.
//   Use for operations that depend on a running kernel but shouldn't be the
//   trigger to start it (e.g., saving, interrupting).
//
// - waitForRuntime: Initializes the runtime (HTTP health check) but does NOT
//   wait for the WebSocket connection or kernel instantiation. Use for
//   operations that only need the HTTP API (e.g., file operations, home page).

type Action =
  | "throwError"
  | "dropRequest"
  | "startConnection"
  | "waitForConnectionOpen"
  | "waitForRuntime";

const ACTIONS: Record<keyof AllRequests, Action> = {
  // These will start a connection if not already connected and then wait until the connection is open
  sendComponentValues: "startConnection",
  sendModelValue: "startConnection",
  sendInstantiate: "startConnection",
  sendRun: "startConnection",
  sendRunScratchpad: "startConnection",

  // Export operations start a connection
  exportAsHTML: "startConnection",
  exportAsIPYNB: "startConnection",
  exportAsMarkdown: "startConnection",
  exportAsPDF: "startConnection",

  // Package operations start a connection (user-initiated install intent)
  addPackage: "startConnection",
  removePackage: "startConnection",

  // sendRestart uses startConnection so it matches sendRun semantics: if the
  // kernel is not running, Restart will spin it up rather than hanging silently.
  // waitForConnectionOpen caused a silent dead-click before the first Run.
  sendRestart: "startConnection",

  // Throw errors for operations that are not supported offline
  sendCopy: "throwError",
  sendFormat: "throwError",
  sendShutdown: "throwError",
  getPackageList: "throwError",
  getDependencyTree: "throwError",

  // These wait until the connection is open, but don't start a connection
  sendSave: "waitForConnectionOpen",
  sendFunctionRequest: "waitForConnectionOpen",
  sendDeleteCell: "waitForConnectionOpen",
  saveAppConfig: "waitForConnectionOpen",
  saveCellConfig: "waitForConnectionOpen",

  // Session-based operations that wait for connection
  sendRename: "waitForConnectionOpen",
  autoExportAsHTML: "waitForConnectionOpen",
  autoExportAsMarkdown: "waitForConnectionOpen",
  autoExportAsIPYNB: "waitForConnectionOpen",
  updateCellOutputs: "waitForConnectionOpen",

  // These wait for connection
  sendStdin: "waitForConnectionOpen",
  sendInterrupt: "waitForConnectionOpen",
  sendPdb: "waitForConnectionOpen",
  sendInstallMissingPackages: "waitForConnectionOpen",
  previewDatasetColumn: "waitForConnectionOpen",
  previewSQLTable: "waitForConnectionOpen",
  previewSQLTableList: "waitForConnectionOpen",
  previewSQLSchemaList: "waitForConnectionOpen",
  previewDataSourceConnection: "waitForConnectionOpen",
  validateSQL: "waitForConnectionOpen",
  listStorageEntries: "waitForConnectionOpen",
  downloadStorage: "waitForConnectionOpen",

  // Sync operations that wait for connection
  sendDocumentTransaction: "waitForConnectionOpen",
  sendCodeCompletionRequest: "waitForConnectionOpen",

  // File operations only need the HTTP API, not the kernel WebSocket
  sendListFiles: "waitForRuntime",
  sendSearchFiles: "waitForRuntime",
  sendCreateFileOrFolder: "waitForRuntime",
  sendDeleteFileOrFolder: "waitForRuntime",
  sendCopyFileOrFolder: "waitForRuntime",
  sendRenameFileOrFolder: "waitForRuntime",
  sendUpdateFile: "waitForRuntime",
  sendFileDetails: "waitForRuntime",
  openFile: "waitForRuntime",
  readCode: "waitForRuntime",

  // Home operations only need the HTTP API, not the kernel WebSocket
  getRecentFiles: "waitForRuntime",
  getWorkspaceFiles: "waitForRuntime",
  getRunningNotebooks: "waitForRuntime",
  shutdownSession: "waitForRuntime",
  openTutorial: "waitForRuntime",
  getUsageStats: "waitForRuntime",

  // Sidebar HTTP-backed operations
  listSecretKeys: "waitForRuntime",
  writeSecret: "waitForRuntime",
  clearCache: "waitForRuntime",
  getCacheInfo: "waitForRuntime",
  saveUserConfig: "waitForRuntime",
};

/**
 * Create a lazy requests client.
 * On any request, we will initialize the runtime manager (if not already initialized)
 * and handle it based on the action type defined in ACTIONS.
 */
export function createLazyRequests(
  delegate: AllRequests,
  getRuntimeManager: () => RuntimeManager,
): AllRequests {
  // Memoize the init call, just once per runtime manager
  const initOnce = memoizeLastValue(async (runtimeManager: RuntimeManager) => {
    store.set(connectionAtom, { state: WebSocketState.CONNECTING });
    await runtimeManager.init();
  });

  // oxlint-disable-next-line typescript/no-explicit-any
  function wrapRequest<T extends (...args: any[]) => Promise<any>>(
    request: T,
    key: keyof AllRequests,
  ): T {
    const action = ACTIONS[key];

    const wrapped = (async (...args) => {
      const runtimeManager = getRuntimeManager();

      // Non-lazy runtime: all requests bypass the lazy wrapper since
      // the runtime is already connecting. File/home operations that
      // need the health check now use apiCall() directly.
      if (!runtimeManager.isLazy) {
        return request(...args);
      }

      switch (action) {
        case "dropRequest":
          Logger.debug(
            `Dropping request: ${key}, since not connected to a kernel.`,
          );
          // Silently drop the request
          return;

        case "throwError":
          throw new NoKernelConnectedError();

        case "waitForConnectionOpen":
          // Wait for connection but don't start it
          await waitForConnectionOpen();
          await waitForKernelToBeInstantiated();
          return request(...args);

        case "waitForRuntime":
          // Wait for the runtime HTTP API to be healthy, but don't
          // touch connectionAtom or wait for WebSocket/kernel.
          await runtimeManager.waitForHealthy();
          return request(...args);

        case "startConnection":
          // Start connection and wait for it to be open
          await initOnce(runtimeManager);
          await waitForConnectionOpen();
          if (key !== "sendInstantiate") {
            // We don't need to wait for kernel to be instantiated if we are sending an instantiate request
            // otherwise we will wait forever
            await waitForKernelToBeInstantiated();
          }
          return request(...args);

        default:
          // This should never happen if ACTIONS is complete
          throw new Error(`Unknown action for "${key}"`);
      }
    }) as T;
    return wrapped;
  }

  return Objects.mapValues(delegate, (value, key) => {
    return wrapRequest(value, key);
  }) as AllRequests;
}

export const visibleForTesting = {
  ACTIONS,
};
