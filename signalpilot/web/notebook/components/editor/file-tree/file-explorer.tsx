import { useAtom, useAtomValue } from "jotai";
import { atomWithStorage } from "jotai/utils";
import { spApiUrl } from "@/core/network/api";
import { isConnectedAtom } from "@/core/network/connection";
import { classifyFile } from "@/core/active-file";
import { openFileInTab } from "@/core/file-tabs";
import {
  ArrowLeftIcon,
  BetweenHorizontalStartIcon,
  BracesIcon,
  CloudIcon,
  CloudOffIcon,
  CopyMinusIcon,
  DownloadIcon,
  ExternalLinkIcon,
  EyeOffIcon,
  FileCodeIcon,
  FilePlus2Icon,
  FolderPlusIcon,
  NotebookPenIcon,
  ListTreeIcon,
  Loader2Icon,
  PlaySquareIcon,
  RefreshCwIcon,
  UploadIcon,
  ViewIcon,
} from "lucide-react";
import React, { Suspense, use, useRef, useState } from "react";
import useResizeObserver from "use-resize-observer";
import {
  type NodeApi,
  type NodeRendererProps,
  Tree,
  type TreeApi,
} from "react-arborist";
import useEvent from "react-use-event-hook";
import {
  FILE_ICON,
  FILE_ICON_COLOR,
  type FileIconType,
  guessFileIconType,
} from "@/components/editor/file-tree/file-icons";
import {
  DeleteMenuItem,
  DuplicateMenuItem,
  FileActionsDropdown,
  RenameMenuItem,
} from "@/components/editor/file-tree/file-operations";
import { FileNameInput } from "@/components/editor/file-tree/file-name-input";
import {
  MENU_ITEM_ICON_CLASS,
  RefreshIconButton,
  TreeChevron,
} from "@/components/editor/file-tree/tree-actions";
import { Spinner } from "@/components/icons/spinner";
import { useImperativeModal } from "@/components/modal/ImperativeModal";
import { AlertDialogDestructiveAction } from "@/components/ui/alert-dialog";
import { Button, buttonVariants } from "@/components/ui/button";
import {
  DropdownMenuItem,
  DropdownMenuSeparator,
} from "@/components/ui/dropdown-menu";
import { Tooltip } from "@/components/ui/tooltip";
import { toast } from "@/components/ui/use-toast";
import { useCellActions } from "@/core/cells/cells";
import { useLastFocusedCellId } from "@/core/cells/focus";
import { disableFileDownloadsAtom } from "@/core/config/config";
import { useRequestClient } from "@/core/network/requests";
import type { FileInfo } from "@/core/network/types";

import { useAsyncData } from "@/hooks/useAsyncData";
import { ErrorBanner } from "@/plugins/impl/common/error-banner";
import { deserializeBlob } from "@/utils/blob";
import { cn } from "@/utils/cn";
import { copyToClipboard } from "@/utils/copy";
import { downloadBlob } from "@/utils/download";
import { type Base64String, base64ToDataURL } from "@/utils/json/base64";
import { openNotebook } from "@/utils/links";
import type { FilePath } from "@/utils/paths";
import { makeDuplicateName } from "@/utils/pathUtils";
import { jotaiJsonStorage } from "@/utils/storage/jotai";
import { getGatewayProjectId } from "@/core/network/api";
import { getApiHeaders } from "@/core/network/api-headers";
import { BranchStatus } from "../chrome/wrapper/footer-items/branch-status";
import { useTreeDndManager } from "./dnd-wrapper";
import { FileViewer } from "./file-viewer";
import type { RequestingTree } from "./requesting-tree";
import { openStateAtom, treeAtom } from "./state";
import { PYTHON_CODE_FOR_FILE_TYPE } from "./types";
import { useFileExplorerUpload } from "./upload";

const hiddenFilesState = atomWithStorage(
  "sp:showHiddenFiles",
  true,
  jotaiJsonStorage,
  {
    getOnInit: true,
  },
);

const RequestingTreeContext = React.createContext<RequestingTree | null>(null);
const GitChangedFilesContext = React.createContext<Set<string>>(new Set());

export const FileExplorer: React.FC<{
  height: number;
}> = ({ height }) => {
  const treeRef = useRef<TreeApi<FileInfo>>(null);
  const { ref: cloudBarRef, height: cloudBarHeight = 0 } = useResizeObserver<HTMLDivElement>();
  const dndManager = useTreeDndManager();
  const [tree] = useAtom(treeAtom);
  const isConnected = useAtomValue(isConnectedAtom);
  const [data, setData] = useState<FileInfo[]>([]);
  const [openFile, setOpenFile] = useState<FileInfo | null>(null);
  const [gitChangedFiles, setGitChangedFiles] = useState<Set<string>>(new Set());
  const [showHiddenFiles, setShowHiddenFiles] =
    useAtom<boolean>(hiddenFilesState);

  const { openPrompt } = useImperativeModal();
  // Keep external state to remember which folders are open
  // when this component is unmounted
  const [openState, setOpenState] = useAtom(openStateAtom);
  const { isPending, error } = useAsyncData(async () => {
    await tree.initialize(setData);
    // Re-expand previously open directories. Clear entries that
    // no longer exist (stale from a different project).
    const openIds = Object.keys(openState)
      .filter((id) => openState[id])
      .toSorted((a, b) => a.length - b.length);
    const validIds: Record<string, boolean> = {};
    for (const id of openIds) {
      const ok = await tree.expand(id);
      if (ok) validIds[id] = true;
    }
    if (Object.keys(validIds).length !== openIds.length) {
      setOpenState(validIds);
    }
  }, [tree, isConnected]);

  // No FS event subscription: cross-process FS sync is unreliable and the wipe-on-event pattern caused user-visible bugs. Use the refresh button.
  const handleRefresh = useEvent(() => {
    // Return the promise so callers can await refresh completion
    return tree.refresh(
      Object.keys(openState).filter((id) => openState[id]),
    );
  });

  const handleHiddenFilesToggle = useEvent(() => {
    const newValue = !showHiddenFiles;
    setShowHiddenFiles(newValue);
  });

  const handleCreateFolder = useEvent(async () => {
    openPrompt({
      title: "Folder name",
      onConfirm: async (name) => {
        tree.createFolder(name, null);
      },
    });
  });

  const handleCreateFile = useEvent(async () => {
    openPrompt({
      title: "File name",
      onConfirm: async (name) => {
        tree.createFile({ name, parentId: null });
      },
    });
  });

  const handleCreateNotebook = useEvent(async () => {
    openPrompt({
      title: "Notebook name",
      onConfirm: async (name) => {
        tree.createFile({ name, parentId: null, type: "notebook" });
      },
    });
  });

  const handleCollapseAll = useEvent(() => {
    treeRef.current?.closeAll();
    setOpenState({});
  });

  // Fetch git changed files for highlighting
  React.useEffect(() => {
    if (!getGatewayProjectId()) {return;}

    getApiHeaders().then((hdrs) =>
      fetch(spApiUrl("/git/status"), { method: "POST", headers: hdrs })
    )
      .then((r) => r.ok ? r.json() as Promise<{ staged?: { path: string }[]; changed?: { path: string }[]; untracked?: { path: string }[] }> : null)
      .then((s) => {
        if (!s) {return;}
        const paths = new Set<string>();
        for (const f of [...(s.staged ?? []), ...(s.changed ?? []), ...(s.untracked ?? [])]) {
          paths.add(f.path);
        }
        setGitChangedFiles(paths);
      })
      .catch(() => {});
  }, [data]);

  const visibleData = React.useMemo(
    () => filterHiddenTree(data, showHiddenFiles),
    [data, showHiddenFiles],
  );

  if (isPending) {
    return <Spinner size="medium" centered={true} />;
  }

  if (error) {
    return <ErrorBanner error={error} />;
  }

  if (openFile) {
    return (
      <>
        <div className="flex items-center pl-1 pr-3 shrink-0 border-b justify-between">
          <Button
            onClick={() => setOpenFile(null)}
            data-testid="file-explorer-back-button"
            variant="text"
            size="xs"
            className="mb-0"
          >
            <ArrowLeftIcon size={16} />
          </Button>
          <span className="font-bold">{openFile.name}</span>
        </div>
        <Suspense>
          <FileViewer
            onOpenNotebook={(evt) =>
              openSpNotebook(
                evt,
                tree.relativeFromRoot(openFile.path as FilePath),
              )
            }
            file={openFile}
          />
        </Suspense>
      </>
    );
  }

  const isCloudProject = !!getGatewayProjectId();

  return (
    <>
      {isCloudProject && <div ref={cloudBarRef}><CloudSyncBar onSynced={handleRefresh} /></div>}
      <Toolbar
        onRefresh={handleRefresh}
        onHidden={handleHiddenFilesToggle}
        onCreateFile={handleCreateFile}
        onCreateNotebook={handleCreateNotebook}
        onCreateFolder={handleCreateFolder}
        onCollapseAll={handleCollapseAll}
        tree={tree}
      />
      <GitChangedFilesContext value={gitChangedFiles}>
      <RequestingTreeContext value={tree}>
        <Tree<FileInfo>
          width="100%"
          ref={treeRef}
          height={height - 33 - cloudBarHeight}
          className="h-full"
          data={visibleData}
          initialOpenState={openState}
          openByDefault={false}
          // Use shared DnD manager to prevent "Cannot have two HTML5 backends" error
          dndManager={dndManager}
          // Hide the drop cursor
          renderCursor={() => null}
          // Disable dropping files into files
          disableDrop={({ parentNode }) => !parentNode.data.isDirectory}
          onDelete={async ({ ids }) => {
            for (const id of ids) {
              await tree.delete(id);
            }
          }}
          onRename={async ({ id, name }) => {
            await tree.rename(id, name);
          }}
          onMove={async ({ dragIds, parentId }) => {
            await tree.move(dragIds, parentId);
          }}
          onSelect={(nodes) => {
            const first = nodes[0];
            if (!first) {
              return;
            }
            if (!first.data.isDirectory) {
              const fileType = classifyFile(first.data.name);
              if (fileType === "raw" || fileType === "notebook") {
                const tab = openFileInTab(first.data.path);
                if (tab.type === "notebook") {
                  // Navigate to the notebook's dedicated session
                  openNotebook(first.data.path);
                }
              } else {
                setOpenFile(first.data);
              }
            }
          }}
          onToggle={async (id) => {
            const result = await tree.expand(id);
            if (result) {
              const prevOpen = openState[id] ?? false;
              setOpenState({ ...openState, [id]: !prevOpen });
            }
          }}
          padding={15}
          rowHeight={30}
          indent={INDENT_STEP}
          overscanCount={1000}
          // Disable multi-selection
          disableMultiSelection={true}
        >
          {Node}
        </Tree>
      </RequestingTreeContext>
      </GitChangedFilesContext>
    </>
  );
};

const INDENT_STEP = 15;

interface ToolbarProps {
  onRefresh: () => void;
  onHidden: () => void;
  onCreateFile: () => void;
  onCreateNotebook: () => void;
  onCreateFolder: () => void;
  onCollapseAll: () => void;
  tree: RequestingTree;
}

const Toolbar = ({
  onRefresh,
  onHidden,
  onCreateFile,
  onCreateNotebook,
  onCreateFolder,
  onCollapseAll,
}: ToolbarProps) => {
  const { getRootProps, getInputProps } = useFileExplorerUpload({
    noDrag: true,
    noDragEventsBubbling: true,
  });

  return (
    <div className="flex items-center justify-end px-2 shrink-0 border-b">
      <Tooltip content="Add notebook">
        <Button
          data-testid="file-explorer-add-notebook-button"
          onClick={onCreateNotebook}
          variant="text"
          size="xs"
        >
          <NotebookPenIcon size={16} />
        </Button>
      </Tooltip>
      <Tooltip content="Add file">
        <Button
          data-testid="file-explorer-add-file-button"
          onClick={onCreateFile}
          variant="text"
          size="xs"
        >
          <FilePlus2Icon size={16} />
        </Button>
      </Tooltip>
      <Tooltip content="Add folder">
        <Button
          data-testid="file-explorer-add-folder-button"
          onClick={onCreateFolder}
          variant="text"
          size="xs"
        >
          <FolderPlusIcon size={16} />
        </Button>
      </Tooltip>
      <Tooltip content="Upload file">
        <button
          data-testid="file-explorer-upload-button"
          {...getRootProps({})}
          className={buttonVariants({
            variant: "text",
            size: "xs",
          })}
        >
          <UploadIcon size={16} />
        </button>
      </Tooltip>
      <input {...getInputProps({})} type="file" />
      <RefreshIconButton
        data-testid="file-explorer-refresh-button"
        onClick={onRefresh}
      />
      <Tooltip content="Toggle hidden files">
        <Button
          data-testid="file-explorer-hidden-files-button"
          onClick={onHidden}
          variant="text"
          size="xs"
        >
          <EyeOffIcon size={16} />
        </Button>
      </Tooltip>
      <Tooltip content="Collapse all folders">
        <Button
          data-testid="file-explorer-collapse-button"
          onClick={onCollapseAll}
          variant="text"
          size="xs"
        >
          <CopyMinusIcon size={16} />
        </Button>
      </Tooltip>
    </div>
  );
};

const Show = ({
  node,
  onOpenFile,
}: {
  node: NodeApi<FileInfo>;
  onOpenFile: (
    evt: Pick<Event, "stopPropagation" | "preventDefault">,
  ) => void;
}) => {
  return (
    <span
      className="flex-1 overflow-hidden text-ellipsis"
      onClick={(e) => {
        if (node.data.isDirectory) {
          return;
        }
        e.stopPropagation();
        node.select();
      }}
    >
      {node.data.name}
      {node.data.isSpFile && (
        <span
          data-testid="file-explorer-open-sp-button"
          className="shrink-0 ml-2 text-sm hidden group-hover:inline hover:underline"
          onClick={onOpenFile}
        >
          open <ExternalLinkIcon className="inline ml-1" size={12} />
        </span>
      )}
    </span>
  );
};

const Node = ({ node, style, dragHandle }: NodeRendererProps<FileInfo>) => {
  const { openFile, sendFileDetails } = useRequestClient();
  const disableFileDownloads = useAtomValue(disableFileDownloadsAtom);
  const gitChanged = React.use(GitChangedFilesContext);

  const fileType: FileIconType = node.data.isDirectory
    ? "directory"
    : guessFileIconType(node.data.name);

  // Check if this file has git changes. Git returns project-relative paths,
  // tree may use absolute paths from the synced dir. Match by suffix.
  const normalizedPath = node.data.path.replace(/\\/g, "/");
  const isGitChanged = !node.data.isDirectory && (
    gitChanged.has(normalizedPath) ||
    [...gitChanged].some((gp) => normalizedPath.endsWith("/" + gp) || normalizedPath === gp)
  );

  const Icon = FILE_ICON[fileType];
  const { openConfirm, openPrompt } = useImperativeModal();
  const { createNewCell } = useCellActions();
  const lastFocusedCellId = useLastFocusedCellId();

  const handleInsertCode = (code: string) => {
    createNewCell({
      code,
      before: false,
      cellId: lastFocusedCellId ?? "__end__",
    });
  };

  const tree = use(RequestingTreeContext);

  const handleOpenFile = async (
    evt: Pick<Event, "stopPropagation" | "preventDefault">,
  ) => {
    const path = tree
      ? tree.relativeFromRoot(node.data.path as FilePath)
      : node.data.path;
    openSpNotebook(evt, path);
  };

  const handleDeleteFile = async (evt: Event) => {
    evt.stopPropagation();
    evt.preventDefault();
    openConfirm({
      title: "Delete file",
      description: `Are you sure you want to delete ${node.data.name}?`,
      confirmAction: (
        <AlertDialogDestructiveAction
          onClick={async () => {
            await node.tree.delete(node.id);
          }}
          aria-label="Confirm"
        >
          Delete
        </AlertDialogDestructiveAction>
      ),
    });
  };

  const handleCreateFolder = useEvent(async () => {
    // If not expanded, then expand
    node.open();
    openPrompt({
      title: "Folder name",
      onConfirm: async (name) => {
        tree?.createFolder(name, node.id);
      },
    });
  });

  const handleCreateFile = useEvent(async () => {
    node.open();
    openPrompt({
      title: "File name",
      onConfirm: async (name) => {
        tree?.createFile({ name, parentId: node.id });
      },
    });
  });

  const handleCreateNotebook = useEvent(async () => {
    node.open();
    openPrompt({
      title: "Notebook name",
      onConfirm: async (name) => {
        tree?.createFile({ name, parentId: node.id, type: "notebook" });
      },
    });
  });

  const handleDuplicate = useEvent(async () => {
    if (!tree) {
      return;
    }
    await tree.copy(node.id, makeDuplicateName(node.data.name));
  });

  return (
    <div
      style={style}
      ref={dragHandle}
      className={cn(
        "flex items-center cursor-pointer ml-1 text-muted-foreground whitespace-nowrap group",
      )}
      draggable={true}
      onClick={(evt) => {
        evt.stopPropagation();
        if (node.data.isDirectory) {
          node.toggle();
        }
      }}
    >
      <FolderArrow node={node} />
      <span
        className={cn(
          "flex items-center pl-1 py-1 cursor-pointer hover:bg-accent/50 hover:text-accent-foreground rounded-l flex-1 overflow-hidden group",
          node.willReceiveDrop &&
            node.data.isDirectory &&
            "bg-accent/80 hover:bg-accent/80 text-accent-foreground",
          isGitChanged && "text-green-400",
        )}
      >
        {node.data.isSpFile ? (
          <FileCodeIcon className="w-5 h-5 shrink-0 mr-2" strokeWidth={1.5} />
        ) : (
          <Icon
            className={cn("w-5 h-5 shrink-0 mr-2", FILE_ICON_COLOR[fileType])}
            strokeWidth={1.5}
          />
        )}
        {node.isEditing ? (
          <FileNameInput node={node} />
        ) : (
          <Show node={node} onOpenFile={handleOpenFile} />
        )}
        <FileActionsDropdown
          testId="file-explorer-more-button"
          iconClassName="w-5 h-5"
        >
          {!node.data.isDirectory && (
            <DropdownMenuItem
              onSelect={() => node.select()}
              data-testid="file-explorer-open-file-menu-item"
            >
              <ViewIcon className={MENU_ITEM_ICON_CLASS} />
              Open file
            </DropdownMenuItem>
          )}
          {!node.data.isDirectory && (
            <DropdownMenuItem
              onSelect={() => {
                openFile({ path: node.data.path });
              }}
              data-testid="file-explorer-open-external-menu-item"
            >
              <ExternalLinkIcon className={MENU_ITEM_ICON_CLASS} />
              Open file in external editor
            </DropdownMenuItem>
          )}
          {node.data.isDirectory && (
            <>
              <DropdownMenuItem
                onSelect={() => handleCreateNotebook()}
                data-testid="file-explorer-create-notebook-menu-item"
              >
                <NotebookPenIcon className={MENU_ITEM_ICON_CLASS} />
                Create notebook
              </DropdownMenuItem>
              <DropdownMenuItem
                onSelect={() => handleCreateFile()}
                data-testid="file-explorer-create-file-menu-item"
              >
                <FilePlus2Icon className={MENU_ITEM_ICON_CLASS} />
                Create file
              </DropdownMenuItem>
              <DropdownMenuItem
                onSelect={() => handleCreateFolder()}
                data-testid="file-explorer-create-folder-menu-item"
              >
                <FolderPlusIcon className={MENU_ITEM_ICON_CLASS} />
                Create folder
              </DropdownMenuItem>
              <DropdownMenuSeparator />
            </>
          )}
          <RenameMenuItem
            onSelect={() => node.edit()}
            testId="file-explorer-rename-menu-item"
          />
          <DuplicateMenuItem
            onSelect={handleDuplicate}
            testId="file-explorer-duplicate-menu-item"
          />
          <DropdownMenuItem
            onSelect={async () => {
              await copyToClipboard(node.data.path);
              toast({ title: "Copied to clipboard" });
            }}
            data-testid="file-explorer-copy-path-menu-item"
          >
            <ListTreeIcon className={MENU_ITEM_ICON_CLASS} />
            Copy path
          </DropdownMenuItem>
          {tree && (
            <DropdownMenuItem
              onSelect={async () => {
                await copyToClipboard(
                  tree.relativeFromRoot(node.data.path as FilePath),
                );
                toast({ title: "Copied to clipboard" });
              }}
              data-testid="file-explorer-copy-relative-path-menu-item"
            >
              <ListTreeIcon className={MENU_ITEM_ICON_CLASS} />
              Copy relative path
            </DropdownMenuItem>
          )}
          <DropdownMenuSeparator />
          <DropdownMenuItem
            onSelect={() => {
              const { path } = node.data;
              const pythonCode = PYTHON_CODE_FOR_FILE_TYPE[fileType](path);
              handleInsertCode(pythonCode);
            }}
            data-testid="file-explorer-insert-snippet-menu-item"
          >
            <BetweenHorizontalStartIcon className={MENU_ITEM_ICON_CLASS} />
            Insert snippet for reading file
          </DropdownMenuItem>
          <DropdownMenuItem
            onSelect={async () => {
              toast({
                title: "Copied to clipboard",
                description:
                  "Code to open the file has been copied to your clipboard. You can also drag and drop this file into the editor",
              });
              const { path } = node.data;
              const pythonCode = PYTHON_CODE_FOR_FILE_TYPE[fileType](path);
              await copyToClipboard(pythonCode);
            }}
            data-testid="file-explorer-copy-snippet-menu-item"
          >
            <BracesIcon className={MENU_ITEM_ICON_CLASS} />
            Copy snippet for reading file
          </DropdownMenuItem>
          {node.data.isSpFile && (
            <>
              <DropdownMenuSeparator />
              <DropdownMenuItem
                onSelect={handleOpenFile}
                data-testid="file-explorer-open-notebook-menu-item"
              >
                <PlaySquareIcon className={MENU_ITEM_ICON_CLASS} />
                Open notebook
              </DropdownMenuItem>
            </>
          )}
          <DropdownMenuSeparator />
          {!node.data.isDirectory && !disableFileDownloads && (
            <>
              <DropdownMenuItem
                onSelect={async () => {
                  const details = await sendFileDetails({
                    path: node.data.path,
                  });
                  if (details.isBase64 && details.contents) {
                    const blob = deserializeBlob(
                      base64ToDataURL(
                        details.contents as Base64String,
                        details.mimeType || "application/octet-stream",
                      ),
                    );
                    downloadBlob(blob, node.data.name);
                  } else {
                    downloadBlob(
                      new Blob([details.contents || ""]),
                      node.data.name,
                    );
                  }
                }}
                data-testid="file-explorer-download-menu-item"
              >
                <DownloadIcon className={MENU_ITEM_ICON_CLASS} />
                Download
              </DropdownMenuItem>
              <DropdownMenuSeparator />
            </>
          )}
          <DeleteMenuItem
            onSelect={handleDeleteFile}
            testId="file-explorer-delete-menu-item"
          />
        </FileActionsDropdown>
      </span>
    </div>
  );
};

const FolderArrow = ({ node }: { node: NodeApi<FileInfo> }) => {
  if (!node.data.isDirectory) {
    return <span className="w-4 h-4 shrink-0" />;
  }

  return <TreeChevron isExpanded={node.isOpen} className="w-4 h-4" />;
};

function openSpNotebook(
  event: Pick<Event, "stopPropagation" | "preventDefault">,
  path: string,
) {
  event.stopPropagation();
  event.preventDefault();
  openNotebook(path);
}

// ── Cloud Sync Bar ──────────────────────────────────────────────

import { type FetchStatus, gitFetch, gitPull } from "@/core/branch/branch-state";

type SyncState = "checking" | "synced" | "behind" | "ahead" | "diverged" | "pulling" | "error" | "no-remote";

const CloudSyncBar: React.FC<{ onSynced: () => void }> = ({ onSynced }) => {
  const [state, setState] = React.useState<SyncState>("checking");
  const [fetchInfo, setFetchInfo] = React.useState<FetchStatus | null>(null);
  const [detail, setDetail] = React.useState("");
  const [pulling, setPulling] = React.useState(false);
  const [confirmingReset, setConfirmingReset] = React.useState(false);
  const [resetting, setResetting] = React.useState(false);

  const checkStatus = React.useCallback(async () => {
    setState("checking");
    const result = await gitFetch();
    if (!result) {
      setState("error");
      setDetail("Could not fetch");
      return;
    }
    setFetchInfo(result);
    if (!result.has_remote) {
      setState("no-remote");
      setDetail("Local only (no remote)");
    } else if (result.ahead === 0 && result.behind === 0) {
      setState("synced");
      setDetail("Up to date");
    } else if (result.behind > 0 && result.ahead === 0) {
      setState("behind");
      setDetail(`${result.behind} commit${result.behind > 1 ? "s" : ""} behind`);
    } else if (result.ahead > 0 && result.behind === 0) {
      setState("ahead");
      setDetail(`${result.ahead} unpushed commit${result.ahead > 1 ? "s" : ""}`);
    } else {
      setState("diverged");
      setDetail(`${result.ahead} ahead, ${result.behind} behind`);
    }
  }, []);

  React.useEffect(() => {
    checkStatus();
    const interval = setInterval(checkStatus, 5 * 60 * 1000);
    return () => clearInterval(interval);
  }, [checkStatus]);

  const handlePull = React.useCallback(async () => {
    setPulling(true);
    const result = await gitPull();
    setPulling(false);
    if (result.success) {
      setState("synced");
      setDetail("Pulled successfully");
      onSynced();
    } else if (result.conflict) {
      setState("error");
      setDetail(`Merge conflict in ${result.files?.length || 0} file(s)`);
    } else {
      setState("error");
      setDetail(result.error || "Pull failed");
    }
  }, [onSynced]);

  const handleForceReset = React.useCallback(async () => {
    setResetting(true);
    setConfirmingReset(false);
    setState("checking");
    setDetail("Resetting...");
    try {
      const resp = await fetch(spApiUrl("/git/force-reset"), { method: "POST", headers: await getApiHeaders() });
      const data = await resp.json() as { success?: boolean; file_count?: number; error?: string };
      if (data.success) {
        setState("synced");
        setDetail(`Reset complete: ${data.file_count} files`);
        onSynced();
      } else {
        setState("error");
        setDetail(data.error || "Reset failed");
      }
    } catch (e) {
      setState("error");
      setDetail(String(e));
    }
    setResetting(false);
  }, [onSynced]);

  const statusColor =
    state === "synced" ? "text-green-500" :
    state === "behind" ? "text-yellow-500" :
    state === "ahead" ? "text-blue-500" :
    state === "diverged" ? "text-orange-500" :
    state === "error" ? "text-red-500" :
    "text-muted-foreground";

  const StatusIcon =
    state === "checking" || pulling ? Loader2Icon :
    state === "synced" ? CloudIcon :
    state === "error" ? CloudOffIcon :
    CloudIcon;

  return (
    <div className="flex flex-col shrink-0 border-b">
      <div className="flex items-center gap-1.5 px-2 py-1.5">
        <BranchStatus />
        <div className="flex-1" />

        <Tooltip content={detail || "Checking..."}>
          <div className={cn("flex items-center gap-1 text-[10px]", statusColor)}>
            <StatusIcon size={12} className={state === "checking" || pulling ? "animate-spin" : ""} />
            {state === "synced" && <span>Synced</span>}
            {state === "behind" && <span>{fetchInfo?.behind} behind</span>}
            {state === "ahead" && <span>{fetchInfo?.ahead} ahead</span>}
            {state === "diverged" && <span>Diverged</span>}
            {state === "error" && <span>Error</span>}
            {state === "no-remote" && <span>Local</span>}
          </div>
        </Tooltip>

        <Tooltip content="Fetch from remote">
          <button
            type="button"
            className="p-0.5 rounded hover:bg-muted/50 text-muted-foreground hover:text-foreground"
            onClick={checkStatus}
            disabled={state === "checking" || pulling}
          >
            <RefreshCwIcon size={12} />
          </button>
        </Tooltip>
      </div>

      {/* Behind banner — offer to pull */}
      {(state === "behind" || state === "diverged") && !pulling && (
        <div className="flex items-center gap-2 px-2 py-1.5 bg-yellow-500/10 border-t border-yellow-500/20">
          <CloudIcon size={12} className="text-yellow-500 shrink-0" />
          <span className="text-[11px] text-yellow-500 flex-1">{detail}</span>
          <Button
            variant="outline"
            size="xs"
            className="h-5 text-[10px] border-yellow-500/30 text-yellow-500 hover:bg-yellow-500/10"
            onClick={handlePull}
          >
            Pull
          </Button>
        </div>
      )}

      {/* Ahead banner — remind to push */}
      {state === "ahead" && (
        <div className="flex items-center gap-2 px-2 py-1.5 bg-blue-500/10 border-t border-blue-500/20">
          <CloudIcon size={12} className="text-blue-500 shrink-0" />
          <span className="text-[11px] text-blue-500 flex-1">{detail}</span>
        </div>
      )}

      {/* Error banner with fix option */}
      {state === "error" && !confirmingReset && (
        <div className="flex items-center gap-2 px-2 py-1.5 bg-red-500/10 border-t border-red-500/20">
          <CloudOffIcon size={12} className="text-red-500 shrink-0" />
          <span className="text-[11px] text-red-500 flex-1 truncate">{detail}</span>
          <Button
            variant="outline"
            size="xs"
            className="h-5 text-[10px] border-red-500/30 text-red-500 hover:bg-red-500/10 shrink-0"
            onClick={() => setConfirmingReset(true)}
          >
            Fix now
          </Button>
        </div>
      )}

      {/* Force reset confirmation */}
      {confirmingReset && (
        <div className="flex flex-col gap-1.5 px-2 py-2 bg-red-500/5 border-t border-red-500/20">
          <span className="text-[11px] text-red-400 font-medium">
            Are you sure? This will delete your local repo and re-clone from the remote. You will lose all un-pushed progress.
          </span>
          <div className="flex gap-1.5">
            <Button
              variant="destructive"
              size="xs"
              className="h-5 text-[10px]"
              onClick={handleForceReset}
              disabled={resetting}
            >
              {resetting ? <Loader2Icon size={10} className="animate-spin mr-1" /> : null}
              Yes, reset
            </Button>
            <Button
              variant="ghost"
              size="xs"
              className="h-5 text-[10px]"
              onClick={() => setConfirmingReset(false)}
            >
              Cancel
            </Button>
          </div>
        </div>
      )}
    </div>
  );
};

export function filterHiddenTree(
  list: FileInfo[],
  showHidden: boolean,
): FileInfo[] {
  if (showHidden) {
    return list;
  }

  const out: FileInfo[] = [];
  for (const item of list) {
    if (isDirectoryOrFileHidden(item.name)) {
      continue;
    }
    let next = item;
    if (item.children) {
      const kids = filterHiddenTree(item.children, showHidden);
      if (kids !== item.children) {
        next = { ...item, children: kids };
      }
    }
    out.push(next);
  }
  return out;
}

export function isDirectoryOrFileHidden(filename: string): boolean {
  if (filename.startsWith(".")) {
    return true;
  }
  return false;
}
