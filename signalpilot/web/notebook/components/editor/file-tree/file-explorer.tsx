import { useAtom, useAtomValue } from "jotai";
import { atomWithStorage } from "jotai/utils";
import { classifyFile } from "@/core/active-file";
import {
  ArrowLeftIcon,
  BetweenHorizontalStartIcon,
  BracesIcon,
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
import { BranchStatus } from "../chrome/wrapper/footer-items/branch-status";
import { useTreeDndManager } from "./dnd-wrapper";
import { FileViewer } from "./file-viewer";
import type { RequestingTree } from "./requesting-tree";
import { fileTreeRefreshNonceAtom, openStateAtom, treeAtom } from "./state";
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
  const [data, setData] = useState<FileInfo[]>([]);
  const [openFile, setOpenFile] = useState<FileInfo | null>(null);
  const [gitChangedFiles, setGitChangedFiles] = useState<Set<string>>(new Set());
  const [showHiddenFiles, setShowHiddenFiles] =
    useAtom<boolean>(hiddenFilesState);
  const refreshNonce = useAtomValue(fileTreeRefreshNonceAtom);

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
  }, [tree, refreshNonce]);

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
              if (fileType === "raw" || fileType === "ambiguous") {
                openNotebook(first.data.path);
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

// ── Branch bar ──────────────────────────────────────────────────
//
// Cloud projects get the branch switcher at the top of the file tree.
// The old git fetch/pull/force-reset sync bar is gone: the workspace
// store is the single source of truth and every save is a revision, so
// there is no local repo to drift out of sync.

const CloudSyncBar: React.FC<{ onSynced: () => void }> = () => {
  return (
    <div className="flex items-center gap-1.5 px-2 py-1.5 shrink-0 border-b">
      <BranchStatus />
      <div className="flex-1" />
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
