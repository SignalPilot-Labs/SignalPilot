import { useAtom, useSetAtom } from "jotai";
import {
  ChevronDownIcon,
  ChevronRightIcon,
  ChevronsDownUpIcon,
  ClockIcon,
  ExternalLinkIcon,
  PlayCircleIcon,
  PowerOffIcon,
  RefreshCcwIcon,
  SearchIcon,
} from "lucide-react";
import type React from "react";
import { Suspense, use, useContext, useEffect, useMemo, useRef, useState } from "react";
import { NotionIcon } from "~/components/branding/notion-icon";
import { SpEmbedConfigContext } from "@/embed/SpEmbedConfigContext";
import {
  type NodeApi,
  type NodeRendererProps,
  Tree,
  type TreeApi,
} from "react-arborist";
import { useLocale } from "react-aria";
import useEvent from "react-use-event-hook";
import { MarkdownIcon } from "@/components/editor/cell/code/icons";
import {
  FILE_ICON as FILE_TYPE_ICONS,
  type FileIconType as FileType,
  guessFileIconType as guessFileType,
} from "@/components/editor/file-tree/file-icons";
import { FileNameInput } from "@/components/editor/file-tree/file-name-input";
import {
  DeleteMenuItem,
  DuplicateMenuItem,
  FileActionsDropdown,
  RenameMenuItem,
  useFileOperations,
  useNotebookFileActions,
} from "@/components/editor/file-tree/file-operations";
import { useImperativeModal } from "@/components/modal/ImperativeModal";
import { AlertDialogDestructiveAction } from "@/components/ui/alert-dialog";
import { Button } from "@/components/ui/button";
import { Checkbox } from "@/components/ui/checkbox";
import { DropdownMenuSeparator } from "@/components/ui/dropdown-menu";
import { Label } from "@/components/ui/label";
import { Tooltip } from "@/components/ui/tooltip";
import { toast } from "@/components/ui/use-toast";
import { isSessionId } from "@/core/kernel/session";
import { isNotionTrailParams, notionRequestIdFromSessionId } from "@/core/notion/trail";
import { apiCall } from "@/core/network/api-call";
import type {
  FileInfo,
  RecentFilesResponse,
  RunningNotebooksResponse,
  ShutdownSessionRequest,
  SpFile,
  WorkspaceFilesRequest,
  WorkspaceFilesResponse,
} from "@/core/network/types";
import { combineAsyncData, useAsyncData } from "@/hooks/useAsyncData";
import { useInterval } from "@/hooks/useInterval";
import { useDebouncedCallback } from "@/hooks/useDebounce";
import { useFilesystemEvents } from "@/core/files/use-filesystem-events";
import { Banner } from "@/plugins/impl/common/error-banner";
import { assertExists } from "@/utils/assertExists";
import { cn } from "@/utils/cn";
import { timeAgo } from "@/utils/dates";
import { prettyError } from "@/utils/errors";
import { Maps } from "@/utils/maps";
import { Paths } from "@/utils/paths";
import { asURL } from "@/utils/url";
import { isPlainLeftClick, openNotebook } from "@/utils/links";
import { preconnectKernel } from "@/utils/preconnect";
import { newNotebookURL } from "@/utils/urls";
import { ConfigButton } from "../app-config/app-config-button";
import { ErrorBoundary } from "../editor/boundary/ErrorBoundary";
import { ShutdownButton } from "../editor/controls/shutdown-button";
import {
  Header,
} from "../home/components";
import { DbtProjectActions } from "../home/dbt-project-actions";
import { DbtProjectList } from "../home/dbt-project-list";
import {
  expandedFoldersAtom,
  includeMarkdownAtom,
  RunningNotebooksContext,
  WorkspaceContext,
} from "../home/state";
import { Spinner } from "../icons/spinner";
import { Input } from "../ui/input";
import { tryGetNotebookConfig } from "~/components/notebook/notebook-context";

function isProjectsProduct(): boolean {
  const config = tryGetNotebookConfig();
  if (config?.product === "projects") return true;
  if (config?.product === "notebooks") return false;
  if (config?.project) return true;
  if (typeof window === "undefined") return false;
  return new URLSearchParams(window.location.search).has("project");
}

function isNotionNotebookFile(file: SpFile): boolean {
  return (
    isNotionTrailParams({ file: file.path, sessionId: file.sessionId }) ||
    Boolean(notionRequestIdFromSessionId(file.path))
  );
}

function mergeNotionNotebookFiles(
  runningFiles: SpFile[],
  recentFiles: SpFile[],
): SpFile[] {
  const byPath = new Map<string, SpFile>();
  for (const file of [...runningFiles, ...recentFiles]) {
    if (!isNotionNotebookFile(file)) continue;
    if (!byPath.has(file.path)) {
      byPath.set(file.path, file);
    }
  }
  return [...byPath.values()];
}

const EMPTY_RUNNING_NOTEBOOKS = new Map<string, SpFile>();
const EMPTY_RECENT_FILES: SpFile[] = [];

type GatewayNotionThread = {
  thread_id: string;
  session_id?: string;
  title?: string;
  source?: string;
  notebook_path?: string;
  created_at?: number;
  updated_at?: number;
};

function toNotionTraceFile(thread: GatewayNotionThread): SpFile | null {
  const path = thread.notebook_path || (isSessionId(thread.thread_id) ? thread.thread_id : "");
  if (!path) {
    return null;
  }

  return {
    name: thread.title || Paths.basename(path) || "Notion request",
    path,
    lastModified: thread.updated_at ?? thread.created_at ?? null,
    sessionId: isSessionId(thread.thread_id) ? thread.thread_id : null,
    initializationId: path,
  };
}

function mergeFilesByPath(files: SpFile[]): SpFile[] {
  const byPath = new Map<string, SpFile>();
  for (const file of files) {
    if (!byPath.has(file.path)) {
      byPath.set(file.path, file);
    }
  }
  return [...byPath.values()];
}

const HomePage: React.FC = () => {
  const [nonce, setNonce] = useState(0);
  // Hide the notebook's own settings/back-to-home buttons when embedded in the
  // SignalPilot app (/projects) — the app provides its own header/nav. They
  // still render in the standalone notebook view.
  const isEmbedded = useContext(SpEmbedConfigContext) !== null;
  const notebookConfig = tryGetNotebookConfig();
  const [gatewayNotionFiles, setGatewayNotionFiles] = useState<SpFile[]>([]);

  const recentsResponse = useAsyncData(
    () => apiCall<RecentFilesResponse>("/home/recent_files", {}),
    [],
  );

  useInterval(
    () => {
      setNonce((nonce) => nonce + 1);
    },
    // Refresh every 10 seconds, or when the document becomes visible
    { delayMs: 10_000, whenVisible: true },
  );

  const runningResponse = useAsyncData(async () => {
    const response = await apiCall<RunningNotebooksResponse>(
      "/home/running_notebooks",
      {},
    );
    return Maps.keyBy(response.files, (file) => file.path);
  }, [nonce]);

  const response = combineAsyncData(recentsResponse, runningResponse);

  if (response.error) {
    throw response.error;
  }

  const data = response.data;
  const running = data?.[1] ?? EMPTY_RUNNING_NOTEBOOKS;
  const recentFiles = data?.[0]?.files ?? EMPTY_RECENT_FILES;
  const projectsProduct = isProjectsProduct();
  const notionConnected = notebookConfig?.notionConnected ?? true;
  const runningFiles = useMemo(() => [...running.values()], [running]);
  const notionFiles = useMemo(
    () => mergeNotionNotebookFiles(runningFiles, recentFiles),
    [recentFiles, runningFiles],
  );
  const combinedNotionFiles = useMemo(
    () => mergeFilesByPath([...gatewayNotionFiles, ...notionFiles]),
    [gatewayNotionFiles, notionFiles],
  );
  const plainRunningFiles = useMemo(
    () => runningFiles.filter((file) => !isNotionNotebookFile(file)),
    [runningFiles],
  );
  const plainRecentFiles = useMemo(
    () => recentFiles.filter((file) => !isNotionNotebookFile(file)),
    [recentFiles],
  );

  useEffect(() => {
    let cancelled = false;

    async function loadGatewayNotionFiles() {
      if (!notebookConfig?.notionConnected || !notebookConfig.gatewayUrl) {
        setGatewayNotionFiles([]);
        return;
      }

      const headers: Record<string, string> = {};
      const token = await notebookConfig.getToken().catch(() => null);
      if (token) {
        headers.Authorization = `Bearer ${token}`;
      } else if (notebookConfig.apiKey) {
        headers["X-API-Key"] = notebookConfig.apiKey;
      }

      try {
        const gatewayUrl = notebookConfig.gatewayUrl.replace(/\/$/, "");
        const resp = await fetch(`${gatewayUrl}/api/chat/traces/threads`, {
          headers,
        });
        if (!resp.ok) {
          throw new Error(`HTTP ${resp.status}`);
        }
        const data = (await resp.json()) as { threads?: GatewayNotionThread[] };
        const files = (data.threads ?? [])
          .filter(
            (thread) =>
              thread.source === "notion" ||
              thread.source === "slack" ||
              Boolean(notionRequestIdFromSessionId(thread.thread_id)),
          )
          .map(toNotionTraceFile)
          .filter((file): file is SpFile => file !== null);
        if (!cancelled) {
          setGatewayNotionFiles(files);
        }
      } catch (error) {
        console.warn("Failed to load gateway Notion traces:", error);
        if (!cancelled) {
          setGatewayNotionFiles([]);
        }
      }
    }

    void loadGatewayNotionFiles();

    return () => {
      cancelled = true;
    };
  }, [
    notebookConfig?.apiKey,
    notebookConfig?.gatewayUrl,
    notebookConfig?.getToken,
    notebookConfig?.notionConnected,
  ]);

  if (!data) {
    return <Spinner centered={true} size="xlarge" />;
  }

  return (
    <Suspense>
      <RunningNotebooksContext
        value={{
          runningNotebooks: running,
          setRunningNotebooks: runningResponse.setData,
        }}
      >
        {!isEmbedded && (
          <div className="absolute top-3 right-5 flex gap-3 z-50">
            <ConfigButton showAppConfig={false} />
            <ShutdownButton
              description={`This will shutdown the notebook server and terminate all running notebooks (${running.size}). You'll lose all data that's in memory.`}
            />
          </div>
        )}
        <div className="flex flex-col gap-6 max-w-6xl container pt-5 pb-20 z-10">
          <div className="flex items-center gap-3 mb-2">
            <img src="logo-192.png" alt="SignalPilot logo" className="w-8 h-8" />
            <h1 className="text-sm font-bold tracking-[0.2em] uppercase text-foreground">
              SignalPilot
            </h1>
          </div>
          {projectsProduct ? (
            <>
              <DbtProjectActions onProjectCreated={recentsResponse.refetch} />
              <ErrorBoundary>
                <DbtProjectList onRefresh={recentsResponse.refetch} />
              </ErrorBoundary>
              {notionConnected && <NotionNotebookSection files={combinedNotionFiles} />}
              <NotebookList
                header={<Header Icon={PlayCircleIcon}>Running notebooks</Header>}
                files={plainRunningFiles}
              />
              <NotebookList
                header={<Header Icon={ClockIcon}>Recent notebooks</Header>}
                files={plainRecentFiles}
              />
            </>
          ) : (
            <NotebookRuntimeHome
              runningFiles={plainRunningFiles}
              recentFiles={plainRecentFiles}
              notionFiles={combinedNotionFiles}
              notionConnected={notionConnected}
            />
          )}
        </div>
      </RunningNotebooksContext>
    </Suspense>
  );
};

const NotebookRuntimeHome: React.FC<{
  runningFiles: SpFile[];
  recentFiles: SpFile[];
  notionFiles: SpFile[];
  notionConnected: boolean;
}> = ({ runningFiles, recentFiles, notionFiles, notionConnected }) => {
  const plainRunningFiles = runningFiles.filter((file) => !isNotionNotebookFile(file));
  const plainRecentFiles = recentFiles.filter((file) => !isNotionNotebookFile(file));

  return (
    <div className="flex flex-col gap-3">
      <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-3">
        <CreateNewNotebook />
      </div>
      <NotebookList
        header={<Header Icon={PlayCircleIcon}>Running notebooks</Header>}
        files={plainRunningFiles}
      />
      <NotebookList
        header={<Header Icon={ClockIcon}>Recent notebooks</Header>}
        files={plainRecentFiles}
      />
      {notionConnected ? (
        <NotionNotebookSection files={notionFiles} />
      ) : (
        <div className="border border-border bg-card px-5 py-10 text-sm text-muted-foreground">
          <p>Connect Notion to generate notebook-backed requests from Notion comments.</p>
          <a
            href="/integrations"
            className="mt-4 inline-flex items-center gap-2 px-4 py-2 text-xs uppercase tracking-wider bg-foreground text-background hover:opacity-90 transition-opacity"
          >
            <NotionIcon className="h-3.5 w-3.5" />
            connect notion
          </a>
        </div>
      )}
    </div>
  );
};

const NotionNotebookSection: React.FC<{ files: SpFile[] }> = ({ files }) => {
  return (
    <div className="flex flex-col gap-3">
      <NotebookList
        header={<Header Icon={NotionIcon}>Notion requests</Header>}
        files={files}
        empty={
          <div className="py-8 text-center text-muted-foreground text-sm">
            <NotionIcon className="mx-auto mb-2 h-6 w-6 opacity-40" />
            <p>No Notion requests found.</p>
            <p className="text-xs mt-1">@ SignalPilot in your Notion workspace.</p>
          </div>
        }
      />
    </div>
  );
};

export const WorkspaceNotebooks: React.FC<{ onRefreshRecents: () => void }> = ({
  onRefreshRecents,
}) => {
  const [includeMarkdown, setIncludeMarkdown] = useAtom(includeMarkdownAtom);
  const [searchText, setSearchText] = useState("");
  const {
    isPending,
    data: workspace,
    error,
    isFetching,
    refetch,
  } = useAsyncData(
    () =>
      apiCall<WorkspaceFilesResponse>("/home/workspace_files", {
        includeMarkdown,
      } satisfies WorkspaceFilesRequest),
    [includeMarkdown],
  );

  // Fire-and-forget refresh of both the workspace tree and the "Recent
  // notebooks" list — file mutations on the workspace tree can affect both,
  // so we invalidate them together rather than having two refresh triggers.
  const refreshWorkspace = useEvent(() => {
    refetch();
    onRefreshRecents();
  });

  const debouncedRefresh = useDebouncedCallback(refreshWorkspace, 250);
  useFilesystemEvents(debouncedRefresh);

  const workspaceContextValue = useMemo(
    () => ({ root: workspace?.root ?? "", refreshWorkspace }),
    [workspace?.root, refreshWorkspace],
  );

  if (isPending) {
    return <Spinner centered={true} size="xlarge" className="mt-6" />;
  }

  if (error) {
    return (
      <Banner kind="danger" className="rounded p-4">
        {prettyError(error)}
      </Banner>
    );
  }

  return (
    <WorkspaceContext value={workspaceContextValue}>
      <div className="flex flex-col gap-2">
        {workspace.hasMore && (
          <Banner kind="warn" className="rounded p-4">
            Showing first {workspace.fileCount} files. Your workspace has more
            files.
          </Banner>
        )}
        <Header
          Icon={BookTextIcon}
          control={
            <div className="flex items-center gap-2">
              <Input
                id="search"
                value={searchText}
                icon={<SearchIcon size={13} />}
                onChange={(e) => setSearchText(e.target.value)}
                placeholder="Search"
                className="mb-0 border-border"
              />
              <CollapseAllButton />
              <Checkbox
                data-testid="include-markdown-checkbox"
                id="include-markdown"
                checked={includeMarkdown}
                onCheckedChange={(checked) =>
                  setIncludeMarkdown(Boolean(checked))
                }
              />
              <Label htmlFor="include-markdown">Include markdown</Label>
            </div>
          }
        >
          Workspace
          <Button
            variant="text"
            size="icon"
            className="w-4 h-4 ml-1 p-0 opacity-70 hover:opacity-100"
            onClick={() => refetch()}
            aria-label="Refresh workspace"
          >
            <RefreshCcwIcon className="w-4 h-4" />
          </Button>
          {isFetching && <Spinner size="small" />}
        </Header>
        <div className="flex flex-col divide-y divide-border border border-border overflow-hidden max-h-192 overflow-y-auto bg-card">
          <NotebookFileTree searchText={searchText} files={workspace.files} />
        </div>
      </div>
    </WorkspaceContext>
  );
};

const CollapseAllButton: React.FC = () => {
  const setOpenState = useSetAtom(expandedFoldersAtom);
  return (
    <Button
      variant="text"
      size="sm"
      className="h-fit hidden sm:flex"
      onClick={() => {
        setOpenState({});
      }}
    >
      <ChevronsDownUpIcon className="w-4 h-4 mr-1" />
      Collapse all
    </Button>
  );
};

const NotebookFileTree: React.FC<{
  files: FileInfo[];
  searchText?: string;
}> = ({ files, searchText }) => {
  const [openState, setOpenState] = useAtom(expandedFoldersAtom);
  const openStateIsEmpty = Object.keys(openState).length === 0;
  const ref = useRef<TreeApi<FileInfo>>(undefined);
  const { root, refreshWorkspace } = use(WorkspaceContext);
  const { renameFile } = useFileOperations({ root });

  useEffect(() => {
    // If empty, collapse all
    if (openStateIsEmpty) {
      ref.current?.closeAll();
    }
  }, [openStateIsEmpty]);

  const handleRename = useEvent(async (id: string, name: string) => {
    const node = ref.current?.get(id);
    if (!node) {
      toast({
        title: "Failed",
        description: `Node with id ${id} not found in the tree`,
      });
      return;
    }
    const result = await renameFile(node.data, name);
    if (result) {
      refreshWorkspace();
    }
  });

  if (files.length === 0) {
    return (
      <div className="flex flex-col px-5 py-10 items-center justify-center">
        <p className="text-center text-muted-foreground">
          No files in this workspace
        </p>
      </div>
    );
  }

  return (
    <Tree<FileInfo>
      ref={ref}
      width="100%"
      height={500}
      searchTerm={searchText}
      className="h-full"
      idAccessor={(data) => data.path}
      data={files}
      openByDefault={false}
      initialOpenState={openState}
      onToggle={async (id) => {
        const prevOpen = openState[id] ?? false;
        setOpenState({ ...openState, [id]: !prevOpen });
      }}
      onRename={async ({ id, name }) => {
        await handleRename(id, name);
      }}
      padding={5}
      rowHeight={35}
      indent={15}
      overscanCount={1000}
      // Hide the drop cursor
      renderCursor={() => null}
      // Disable interactions
      disableDrop={true}
      disableDrag={true}
      disableMultiSelection={true}
    >
      {Node}
    </Tree>
  );
};

const Node = ({ node, style }: NodeRendererProps<FileInfo>) => {
  const fileType: FileType = node.data.isDirectory
    ? "directory"
    : guessFileType(node.data.name);

  const Icon = FILE_TYPE_ICONS[fileType];
  const iconEl = <Icon className="w-5 h-5 shrink-0" strokeWidth={1.5} />;
  const { root } = use(WorkspaceContext);
  const { runningNotebooks } = use(RunningNotebooksContext);

  const renderItem = () => {
    const itemClassName =
      "flex items-center pl-1 cursor-pointer hover:bg-accent/50 hover:text-accent-foreground rounded-l flex-1 overflow-hidden h-full pr-3 gap-2";

    // Inline rename input; react-arborist flips `node.isEditing` when
    // `node.edit()` is called from the FileActions menu.
    if (node.isEditing) {
      return (
        <div className={itemClassName}>
          {iconEl}
          <FileNameInput node={node} />
        </div>
      );
    }

    if (node.data.isDirectory) {
      return (
        <span className={itemClassName}>
          {iconEl}
          {node.data.name}
        </span>
      );
    }

    const relativePath =
      node.data.path.startsWith(root) && Paths.isAbsolute(node.data.path)
        ? Paths.rest(node.data.path, root)
        : node.data.path;

    const isMarkdown =
      relativePath.endsWith(".md") || relativePath.endsWith(".qmd");
    const isRunning = runningNotebooks.has(relativePath);

    return (
      <a
        className={itemClassName}
        href={asURL(`?file=${encodeURIComponent(relativePath)}`).toString()}
        target="_self"
        onMouseEnter={preconnectKernel}
        onFocus={preconnectKernel}
        onClick={(e) => {
          if (!isPlainLeftClick(e)) return;
          e.preventDefault();
          openNotebook(relativePath);
        }}
      >
        {iconEl}
        <span className="flex-1 overflow-hidden text-ellipsis">
          {node.data.name}
          {isMarkdown && <MarkdownIcon className="ml-2 inline opacity-80" />}
        </span>

        <FileActions node={node} isRunning={isRunning} />
        {/*
          Trailing action slots. Using a fixed-width row here (rather than
          conditionally rendered inline elements) keeps every row's right
          edge aligned even though any individual slot may be empty.
        */}
        <div className="w-8 h-8 flex items-center justify-center shrink-0">
          <SessionShutdownButton filePath={relativePath} />
        </div>
        <ExternalLinkIcon
          size={20}
          className="group-hover:opacity-100 opacity-0 text-primary shrink-0"
        />
      </a>
    );
  };

  return (
    <div
      style={style}
      className={cn(
        "flex items-center cursor-pointer ml-1 text-muted-foreground whitespace-nowrap group h-full",
      )}
      onClick={(evt) => {
        evt.stopPropagation();
        if (node.data.isDirectory) {
          node.toggle();
        }
      }}
    >
      <FolderArrow node={node} />
      {renderItem()}
    </div>
  );
};

const FileActions = ({
  node,
  isRunning,
}: {
  node: NodeApi<FileInfo>;
  isRunning: boolean;
}) => {
  const { root, refreshWorkspace } = use(WorkspaceContext);
  const { handleRename, handleDuplicate, handleDelete } =
    useNotebookFileActions({ node, root, onAfterChange: refreshWorkspace });

  const lockedReason = isRunning
    ? "Stop the notebook's kernel before renaming or deleting."
    : undefined;

  return (
    <FileActionsDropdown
      testId="workspace-more-button"
      buttonClassName="w-8 h-8 p-0 shrink-0"
      contentClassName="print:hidden w-fit min-w-[140px]"
      preventDefaultOnTrigger={true}
    >
      <RenameMenuItem
        onSelect={handleRename}
        disabled={isRunning}
        title={lockedReason}
      />
      <DuplicateMenuItem onSelect={handleDuplicate} />
      <DropdownMenuSeparator />
      <DeleteMenuItem
        onSelect={handleDelete}
        disabled={isRunning}
        title={lockedReason}
      />
    </FileActionsDropdown>
  );
};

const FolderArrow = ({ node }: { node: NodeApi<FileInfo> }) => {
  if (!node.data.isDirectory) {
    return <span className="w-5 h-5 shrink-0" />;
  }

  return node.isOpen ? (
    <ChevronDownIcon className="w-5 h-5 shrink-0" />
  ) : (
    <ChevronRightIcon className="w-5 h-5 shrink-0" />
  );
};

const NotebookList: React.FC<{
  header: React.ReactNode;
  files: SpFile[];
  empty?: React.ReactNode;
}> = ({ header, files, empty = null }) => {
  if (files.length === 0) {
    return empty;
  }

  return (
    <div className="flex flex-col gap-2">
      {header}
      <div className="flex flex-col divide-y divide-border border border-border overflow-hidden max-h-192 overflow-y-auto bg-card">
        {files.map((file) => {
          return <SpFileComponent key={file.path} file={file} />;
        })}
      </div>
    </div>
  );
};

const SpFileComponent = ({ file }: { file: SpFile }) => {
  const { locale } = useLocale();
  const { runningNotebooks } = use(RunningNotebooksContext);
  const runningSession = runningNotebooks.get(file.path);
  const runningSessionId = runningSession?.sessionId ?? null;
  const linkSessionId = runningSessionId ?? file.sessionId ?? null;

  // If path is a sessionId, then it has not been saved yet
  // We want to keep the sessionId in this case
  const isNewNotebook = isSessionId(file.path);
  const href = isNewNotebook
    ? asURL(
        `?file=${encodeURIComponent(file.initializationId ?? file.path)}&session_id=${file.path}`,
      )
    : asURL(
        `?file=${encodeURIComponent(file.path)}${
          linkSessionId
            ? `&session_id=${encodeURIComponent(linkSessionId)}`
            : ""
        }`,
      );

  const isMarkdown = file.path.endsWith(".md");

  return (
    <a
      className="py-1.5 px-4 hover:bg-muted transition-all duration-200 cursor-pointer group relative flex gap-4 items-center"
      key={file.path}
      href={href.toString()}
      target="_self"
      onMouseEnter={preconnectKernel}
      onFocus={preconnectKernel}
      onClick={(e) => {
        if (isNewNotebook || runningSessionId) return; // session-id notebooks need full nav
        if (!isPlainLeftClick(e)) return;
        e.preventDefault();
        openNotebook(file.path);
      }}
    >
      <div className="flex flex-col justify-between flex-1">
        <span className="flex items-center gap-2">
          {file.name}
          {runningSessionId && (
            <span className="rounded border border-emerald-500/30 px-1.5 py-0.5 text-[10px] uppercase tracking-wide text-emerald-400">
              running
            </span>
          )}
          {isMarkdown && (
            <span className="opacity-80">
              <MarkdownIcon />
            </span>
          )}
        </span>
        <p
          title={file.path}
          className="text-sm text-muted-foreground overflow-hidden whitespace-nowrap text-ellipsis"
        >
          {file.path}
        </p>
      </div>
      <div className="flex flex-col gap-1 items-end">
        <div className="flex gap-3 items-center">
          <div>
            <SessionShutdownButton filePath={file.path} />
          </div>
          <ExternalLinkIcon
            size={20}
            className="group-hover:opacity-100 opacity-0 transition-all duration-300 text-primary"
          />
        </div>
        {!!file.lastModified && (
          <div className="text-xs text-muted-foreground opacity-80">
            {timeAgo(file.lastModified * 1000, locale)}
          </div>
        )}
      </div>
    </a>
  );
};

const SessionShutdownButton: React.FC<{ filePath: string }> = ({
  filePath,
}) => {
  const { openConfirm, closeModal } = useImperativeModal();
  const { runningNotebooks, setRunningNotebooks } = use(
    RunningNotebooksContext,
  );
  if (!runningNotebooks.has(filePath)) {
    return null;
  }
  return (
    <Tooltip content="Shutdown">
      <Button
        size={"icon"}
        variant="outline"
        className="opacity-80 hover:opacity-100 hover:bg-accent text-destructive border-destructive hover:border-destructive hover:text-destructive bg-background hover:bg-(--red-1)"
        onClick={(e) => {
          e.stopPropagation();
          e.preventDefault();
          openConfirm({
            title: "Shutdown",
            description:
              "This will terminate the Python kernel. You'll lose all data that's in memory.",
            variant: "destructive",
            confirmAction: (
              <AlertDialogDestructiveAction
                onClick={() => {
                  const ids = runningNotebooks.get(filePath);
                  assertExists(ids?.sessionId);
                  apiCall<RunningNotebooksResponse>(
                    "/home/shutdown_session",
                    { sessionId: ids.sessionId } satisfies ShutdownSessionRequest,
                  ).then((response) => {
                    setRunningNotebooks(
                      Maps.keyBy(response.files, (file) => file.path),
                    );
                  });
                  closeModal();
                  toast({
                    description: "Notebook has been shutdown.",
                  });
                }}
                aria-label="Confirm Shutdown"
              >
                Shutdown
              </AlertDialogDestructiveAction>
            ),
          });
        }}
      >
        <PowerOffIcon size={14} />
      </Button>
    </Tooltip>
  );
};

export const CreateNewNotebook: React.FC = () => {
  const url = newNotebookURL();
  return (
    <a
      className="relative p-5 group border border-border hover:border-muted-foreground bg-card transition-all duration-200 cursor-pointer"
      href={url}
      target="_blank"
      rel="noreferrer"
    >
      <h2 className="text-xs font-bold tracking-[0.15em] uppercase text-foreground">Create a new notebook</h2>
      <div className="group-hover:opacity-100 opacity-0 absolute right-5 top-0 bottom-0 flex items-center justify-center transition-all duration-200">
        <ExternalLinkIcon size={16} className="text-muted-foreground" />
      </div>
    </a>
  );
};

export default HomePage;
