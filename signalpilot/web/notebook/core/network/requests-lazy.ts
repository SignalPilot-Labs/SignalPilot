import { NoKernelConnectedError } from "@/utils/errors";
import { Logger } from "@/utils/Logger";
import { Objects } from "@/utils/objects";
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

// waitForRuntime keys that can be served by the gateway file plane directly
// (see the waitForRuntime case below).
const FILE_PLANE_KEYS = new Set<keyof AllRequests>([
  "sendListFiles",
  "sendSearchFiles",
  "sendCreateFileOrFolder",
  "sendDeleteFileOrFolder",
  "sendCopyFileOrFolder",
  "sendRenameFileOrFolder",
  "sendUpdateFile",
  "sendFileDetails",
]);

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
  // Init at most once per runtime manager — but forget a FAILED attempt so
  // the next Run can retry (lazy provisioning may fail transiently; caching
  // the rejection would permanently brick the Run button).
  let inFlight: { rm: RuntimeManager; promise: Promise<void> } | null = null;
  const initOnce = (runtimeManager: RuntimeManager): Promise<void> => {
    if (!inFlight || inFlight.rm !== runtimeManager) {
      const promise = (async () => {
        // Never regress an already-open connection to CONNECTING: onOpen
        // fired in the past and will not fire again, so waiters on OPEN
        // would deadlock. Only announce CONNECTING from a cold state.
        if (store.get(connectionAtom).state !== WebSocketState.OPEN) {
          store.set(connectionAtom, { state: WebSocketState.CONNECTING });
        }
        await runtimeManager.init();
      })().catch((error) => {
        inFlight = null;
        if (store.get(connectionAtom).state === WebSocketState.CONNECTING) {
          store.set(connectionAtom, { state: WebSocketState.NOT_STARTED });
        }
        throw error;
      });
      inFlight = { rm: runtimeManager, promise };
    }
    return inFlight.promise;
  };

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

        case "waitForRuntime": {
          // File operations dispatch straight to the gateway workspace store
          // when a project file plane is bound — no sandbox required, works
          // before any runtime exists (sessionless boot).
          if (FILE_PLANE_KEYS.has(key)) {
            const { hasGatewayFilePlane } = await import("./gateway-file-api");
            if (hasGatewayFilePlane()) {
              return request(...args);
            }
          }
          // Wait for the runtime HTTP API to be healthy, but don't
          // touch connectionAtom or wait for WebSocket/kernel.
          await runtimeManager.waitForHealthy();
          return request(...args);
        }

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
