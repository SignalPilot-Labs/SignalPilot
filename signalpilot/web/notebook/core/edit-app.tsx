import { usePrevious } from "@dnd-kit/utilities";
import { Tooltip } from "radix-ui";
import { apiCall } from "@/core/network/api-call";
import { useAtomValue, useSetAtom } from "jotai";
import { useEffect, useRef } from "react";
import { NotebookLoadingState } from "@/components/editor/alerts/connecting-alert";
import { Controls } from "@/components/editor/controls/Controls";
import { AppHeader } from "@/components/editor/header/app-header";
import { FilenameForm } from "@/components/editor/header/filename-form";
import { MultiCellActionToolbar } from "@/components/editor/navigation/multi-cell-action-toolbar";
import { cn } from "@/utils/cn";
import { Paths } from "@/utils/paths";
import { KnownQueryParams } from "./constants";
import { SPA_NAVIGATE_EVENT } from "./router/spa-navigate";
import { activeTabIdAtom, openFileInTab, openTabsAtom, useActiveTab } from "./file-tabs";
import { isSwitchingNotebookAtom } from "./notebook-switcher";
import { dbtProjectDirAtom, dbtProjectInfoAtom } from "@/components/editor/dbt/use-dbt";
import { fileTreeRefreshNonceAtom } from "@/components/editor/file-tree/state";
import type { DbtProjectInfo } from "@/components/editor/dbt/types";
import { gatewayBranchIdAtom } from "@/core/branch/branch-state";
import { getGatewayBranchId, getGatewayProjectId, setGatewayBranchId, setGatewayProjectId } from "./network/api";
import { store } from "./state/jotai";
import { rawFallbackAtom } from "./meta/state";
import { filenameAtom } from "./saving/file-state";
import { updateQueryParams } from "@/utils/urls";
import { AppContainer } from "../components/editor/app-container";
import {
  useRunAllCells,
  useRunStaleCells,
} from "../components/editor/cell/useRunCells";
import { RawFileEditor } from "../components/editor/raw-file-editor";
import { CellArray } from "../components/editor/renderers/cell-array";
import { CellsRenderer } from "../components/editor/renderers/cells-renderer";
import { useHotkey } from "../hooks/useHotkey";
import {
  hasCellsAtom,
  notebookIsRunningAtom,
  numColumnsAtom,
  useCellActions,
} from "./cells/cells";
import type { AppConfig, UserConfig } from "./config/config-schema";
import { RuntimeState } from "./kernel/RuntimeState";
import { getSessionId, setSessionId } from "./kernel/session";
import { useTogglePresenting } from "./layout/useTogglePresenting";
import { viewStateAtom } from "./mode";
import { useRequestClient } from "./network/requests";
import { useFilename } from "./saving/filename";
import { setDocumentTitle } from "./dom/document-title";
import { lastSavedNotebookAtom } from "./saving/state";
import { useSpKernelConnection } from "./websocket/useSpKernelConnection";

const TooltipProvider = Tooltip.Provider;

interface AppProps {
  /**
   * The user config.
   */
  userConfig: UserConfig;
  /**
   * The app config.
   */
  appConfig: AppConfig;
  /**
   * If true, the floating controls will be hidden.
   */
  hideControls?: boolean;
}

export const EditApp: React.FC<AppProps> = ({
  userConfig,
  appConfig,
  hideControls = false,
}) => {
  const { setCells, mergeAllColumns, collapseAllCells, expandAllCells } =
    useCellActions();
  const viewState = useAtomValue(viewStateAtom);
  const numColumns = useAtomValue(numColumnsAtom);
  const hasCells = useAtomValue(hasCellsAtom);
  const filename = useFilename();
  const setLastSavedNotebook = useSetAtom(lastSavedNotebookAtom);
  const { sendComponentValues, sendInterrupt } = useRequestClient();

  const isEditing = viewState.mode === "edit";
  const isPresenting = viewState.mode === "present";
  const isRunning = useAtomValue(notebookIsRunningAtom);

  // Initialize RuntimeState event-listeners
  useEffect(() => {
    RuntimeState.INSTANCE.start(sendComponentValues);
    return () => {
      try { RuntimeState.INSTANCE.stop(); } catch { /* client already disposed */ }
    };
  }, []);

  const { connection, reconnect, forceReconnect } = useSpKernelConnection({
    autoInstantiate: userConfig.runtime.auto_instantiate,
    setCells: (cells, layout) => {
      setCells(cells);
      const names = cells.map((cell) => cell.name);
      const codes = cells.map((cell) => cell.code);
      const configs = cells.map((cell) => cell.config);
      setLastSavedNotebook({ names, codes, configs, layout });
    },
    sessionId: getSessionId(),
  });

  // Update document title whenever filename or app_title changes
  useEffect(() => {
    setDocumentTitle(
      appConfig.app_title ||
        Paths.basename(filename ?? "") ||
        "Untitled Notebook",
    );
  }, [appConfig.app_title, filename]);

  // Delete column breakpoints if app width changes from "columns"
  const previousWidth = usePrevious(appConfig.width);
  useEffect(() => {
    if (previousWidth === "columns" && appConfig.width !== "columns") {
      mergeAllColumns();
    }
  }, [appConfig.width, previousWidth, mergeAllColumns, numColumns]);

  const runStaleCells = useRunStaleCells();
  const runAllCells = useRunAllCells();
  const togglePresenting = useTogglePresenting();

  // HOTKEYS
  useHotkey("global.runStale", () => {
    runStaleCells();
  });
  useHotkey("global.interrupt", () => {
    sendInterrupt();
  });
  useHotkey("global.hideCode", () => {
    togglePresenting();
  });
  useHotkey("global.runAll", () => {
    runAllCells();
  });
  useHotkey("global.collapseAllSections", () => {
    collapseAllCells();
  });
  useHotkey("global.expandAllSections", () => {
    expandAllCells();
  });

  const activeTab = useActiveTab();

  // On mount: read branch from URL, sync cloud project files, set up tabs
  useEffect(() => {
    const init = async () => {
      const params = new URL(window.location.href).searchParams;

      // Hydrate project/branch from URL (shareable links)
      const urlProject = params.get(KnownQueryParams.project);
      const urlBranch = params.get(KnownQueryParams.branch);
      if (urlProject) {setGatewayProjectId(urlProject);}
      if (urlBranch) {
        setGatewayBranchId(urlBranch);
        store.set(gatewayBranchIdAtom, urlBranch);
      }

      const projectId = urlProject || getGatewayProjectId();

      if (projectId && !store.get(dbtProjectDirAtom)) {
        // Cloud project: sync-down if not already synced by NotebookBoot.
        // dbtProjectDirAtom being set means boot already synced.
        try {
          const result = await apiCall<{ local_dir?: string; file_count?: number }>("/project/sync-down", {});
          if (result.local_dir) {
            console.log(`[Sync] Synced ${result.file_count} files to ${result.local_dir}`);
            store.set(dbtProjectDirAtom, result.local_dir);
            store.set(fileTreeRefreshNonceAtom, (n: number) => n + 1);

            // Pre-detect dbt project so the panel is ready when opened.
            // Uses apiCall() which only needs the runtime health check — no kernel.
            apiCall<DbtProjectInfo>("/dbt/project_info", { projectDir: result.local_dir })
              .then((info) => {
                if (info?.found) {
                  store.set(dbtProjectInfoAtom, info);
                }
              })
              .catch(() => {});
          }
        } catch (e) {
          console.error("[Sync] Failed:", e);
        }
        // Sync complete — files are available on the pod.
      } else {
        // No cloud project — nothing to sync.
      }

      const fileInUrl = new URL(window.location.href).searchParams.get("file");
      const isRawFallback = store.get(rawFallbackAtom);
      const storedFilename = store.get(filenameAtom);
      let filePath = isRawFallback && storedFilename ? storedFilename : fileInUrl;

      // Resolve relative file paths to absolute using the synced project dir.
      // URL has "models/schema.yml" but the pod needs the full path.
      const projectDir = store.get(dbtProjectDirAtom);
      if (filePath && projectDir && !filePath.startsWith("/") && !filePath.startsWith("__new__")) {
        filePath = `${projectDir.replace(/\/$/, "")}/${filePath}`;
      }

      if (filePath && !filePath.startsWith("__new__")) {
        console.log("[EditApp.init] opening file tab:", filePath.slice(-50));
        openFileInTab(filePath, isRawFallback);
      } else if (!fileInUrl || fileInUrl.startsWith("__new__")) {
        console.log("[EditApp.init] __new__ project — clearing tabs");
        store.set(openTabsAtom, []);
        store.set(activeTabIdAtom, null);
      }
    };

    init();
  }, []); // Only on mount

  // Ref to track the path of the currently active tab, used by the URL-change
  // listener below to avoid opening a tab that is already active.
  const activeTabPathRef = useRef<string | null>(null);
  useEffect(() => {
    activeTabPathRef.current = activeTab?.path ?? null;
  }, [activeTab?.path]);

  // Listen for URL changes driven by navigate() / popstate (e.g. browser back/
  // forward, home-page link clicks). When the URL's `file` param differs from
  // the currently active tab, open the new file in a tab — identical to the
  // mount-time init path, so WS reconnect and autosave guards all fire.
  useEffect(() => {
    const onUrlChange = () => {
      const params = new URL(window.location.href).searchParams;
      const file = params.get(KnownQueryParams.filePath);
      console.log("[onUrlChange] file param:", file, "activeTabPath:", activeTabPathRef.current?.slice(-30));
      if (!file || file.startsWith("__new__")) return;
      // Resolve relative paths (e.g. "notebooks/intro.py" → "/workspace/.../notebooks/intro.py")
      let filePath = file;
      const projectDir = store.get(dbtProjectDirAtom);
      if (projectDir && !filePath.startsWith("/")) {
        filePath = `${projectDir.replace(/\/$/, "")}/${filePath}`;
      }
      if (activeTabPathRef.current === filePath) {
        console.log("[onUrlChange] same path — skipping");
        return;
      }
      console.log("[onUrlChange] opening:", filePath.slice(-50));
      openFileInTab(filePath);
    };
    window.addEventListener("popstate", onUrlChange);
    window.addEventListener(SPA_NAVIGATE_EVENT, onUrlChange);
    return () => {
      window.removeEventListener("popstate", onUrlChange);
      window.removeEventListener(SPA_NAVIGATE_EVENT, onUrlChange);
    };
  }, []);

  // Keep the URL in sync when switching between files/tabs.
  // Guard: skip the replaceState when the URL already reflects the active file
  // (e.g. immediately after navigate() has written the URL via pushState).
  // This prevents a pushState→replaceState double-drive.
  useEffect(() => {
    updateQueryParams((params) => {
      const projectId = getGatewayProjectId();
      const branchId = getGatewayBranchId();

      if (projectId) {
        params.set(KnownQueryParams.project, projectId);
      }
      if (branchId && projectId) {
        params.set(KnownQueryParams.branch, branchId);
      }

      if (activeTab) {
        const filePath = activeTab.path.replace(/\\/g, "/");
        // Strip the sync directory prefix to get project-relative path
        const syncMarker = "/.sp/projects/";
        const syncIdx = filePath.indexOf(syncMarker);
        let canonicalFilePath: string;
        if (syncIdx !== -1) {
          // Path: .../.sp/projects/{projectId}/{projectName}/models/schema.yml
          // After syncMarker: {projectId}/{projectName}/models/schema.yml
          // We want: models/schema.yml (everything after {projectId}/{projectName})
          const afterSync = filePath.slice(syncIdx + syncMarker.length);
          const segments = afterSync.split("/");
          // Structure: {projectId}/{projectName}/...rest
          if (segments.length > 2) {
            canonicalFilePath = segments.slice(2).join("/");
          } else {
            canonicalFilePath = filePath;
          }
        } else {
          canonicalFilePath = filePath;
        }
        // Only write if the URL doesn't already reflect this file, so we don't
        // create a pushState→replaceState double-drive when navigate() set it.
        const currentFileParam = new URLSearchParams(window.location.search).get(
          KnownQueryParams.filePath,
        );
        if (currentFileParam === canonicalFilePath) return;
        params.set(KnownQueryParams.filePath, canonicalFilePath);
      }
    });
  }, [activeTab, filename]);

  // Reconnect the kernel WS when the active notebook file changes.
  const currentWsPath = useRef<string | null>(null);
  useEffect(() => {
    if (activeTab?.type !== "notebook") {return;}
    const newPath = activeTab.path;
    if (currentWsPath.current === newPath) {return;}

    const wasNull = currentWsPath.current === null;
    currentWsPath.current = newPath;

    // On initial mount the WS hasn't connected yet — skip reconnect.
    // But if cells already exist (kernel session active from a previous
    // file, e.g. __new__project), we MUST reconnect to load the new file.
    if (wasNull && !store.get(hasCellsAtom)) {return;}

    console.log("[WS-RECONNECT] path changed:", newPath.slice(-40), "wasNull:", wasNull);
    store.set(isSwitchingNotebookAtom, true);
    forceReconnect();
  }, [activeTab?.path, activeTab?.type, forceReconnect]);

  // Sync the active tab's path to filenameAtom so the save logic
  // knows the file is persistent (not new/unnamed).
  useEffect(() => {
    if (activeTab?.type === "notebook" && activeTab.path) {
      store.set(filenameAtom, activeTab.path);
    }
  }, [activeTab?.path, activeTab?.type]);

  // Reconnect the kernel WS when the git branch changes.
  // rebootMountConfig() writes gatewayBranchIdAtom; this effect is the
  // sole reconnect trigger — rebootMountConfig does not touch the WS directly.
  const lastBranchId = useRef<string | null>(null);
  const branchId = useAtomValue(gatewayBranchIdAtom);
  useEffect(() => {
    if (lastBranchId.current === null) {
      lastBranchId.current = branchId;
      return;
    }
    if (lastBranchId.current !== branchId) {
      lastBranchId.current = branchId;
      store.set(isSwitchingNotebookAtom, true);
      forceReconnect();
    }
  }, [branchId, forceReconnect]);

  const editableCellsArray = (
    <CellArray
      mode={viewState.mode}
      userConfig={userConfig}
      appConfig={appConfig}
      hideControls={hideControls}
    />
  );

  const renderContent = () => {
    // Active tab is a raw file — show raw file editor
    if (activeTab?.type === "raw") {
      return <RawFileEditor filePath={activeTab.path} />;
    }

    // No tab and no cells — show welcome state
    const fileInUrl = new URL(window.location.href).searchParams.get("file") || "";
    const isProjectEntry = fileInUrl.startsWith("__new__");
    const isNotebookInUrl = fileInUrl.endsWith(".py") || fileInUrl.endsWith(".md") || fileInUrl.endsWith(".qmd");

    if (!activeTab && !hasCells && (!fileInUrl || isProjectEntry) && !isNotebookInUrl) {
      return (
        <div className="flex flex-col items-center justify-center h-full gap-4 text-muted-foreground">
          <div className="text-lg font-semibold text-foreground">
            Select a file to get started
          </div>
          <div className="text-sm max-w-md text-center">
            Use the file tree in the sidebar to open a <code className="text-xs bg-muted rounded px-1">.sql</code>, <code className="text-xs bg-muted rounded px-1">.yml</code>, or <code className="text-xs bg-muted rounded px-1">.py</code> file from your dbt project.
          </div>
        </div>
      );
    }

    // Notebook view (active notebook file or cells already loaded)
    return (
      <>
        <AppHeader
          connection={connection}
          onForceReconnect={forceReconnect}
          className={cn(
            "pt-4 sm:pt-12 pb-2 mb-4 print:hidden z-50",
            "sticky left-0",
          )}
        >
          {isEditing && (
            <div className="flex items-center justify-center container">
              <FilenameForm filename={activeTab?.path ?? filename} />
            </div>
          )}
        </AppHeader>

        {hasCells && (
          <CellsRenderer appConfig={appConfig} mode={viewState.mode}>
            {editableCellsArray}
          </CellsRenderer>
        )}
        {!hasCells && <NotebookLoadingState />}
      </>
    );
  };

  return (
    <>
      {/* <TabBar /> */}
      <AppContainer
        connection={connection}
        isRunning={isRunning}
        width={appConfig.width}
        onReconnect={reconnect}
      >
        {renderContent()}
      </AppContainer>
      <MultiCellActionToolbar />
      {!hideControls && (
        <TooltipProvider>
          <Controls
            presenting={isPresenting}
            onTogglePresenting={togglePresenting}
            onInterrupt={sendInterrupt}
            onRun={runStaleCells}
            onRunAll={runAllCells}
            connectionState={connection.state}
            running={isRunning}
            appConfig={appConfig}
          />
        </TooltipProvider>
      )}
    </>
  );
};
