import {
  BetweenHorizontalStartIcon,
  BracesIcon,
  DownloadIcon,
  ExternalLinkIcon,
  FilePlus2Icon,
  FileCodeIcon,
  FolderPlusIcon,
  ListTreeIcon,
  NotebookPenIcon,
  PlaySquareIcon,
  ViewIcon,
} from "lucide-react";
import React, { use } from "react";
import { type NodeRendererProps } from "react-arborist";
import useEvent from "react-use-event-hook";
import { useAtomValue } from "jotai";
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
import { MENU_ITEM_ICON_CLASS } from "@/components/editor/file-tree/tree-actions";
import { useImperativeModal } from "@/components/modal/ImperativeModal";
import { AlertDialogDestructiveAction } from "@/components/ui/alert-dialog";
import {
  DropdownMenuItem,
  DropdownMenuSeparator,
} from "@/components/ui/dropdown-menu";
import { toast } from "@/components/ui/use-toast";
import { useCellActions } from "@/core/cells/cells";
import { useLastFocusedCellId } from "@/core/cells/focus";
import { disableFileDownloadsAtom } from "@/core/config/config";
import { useRequestClient } from "@/core/network/requests";
import type { FileInfo } from "@/core/network/types";
import { deserializeBlob } from "@/utils/blob";
import { cn } from "@/utils/cn";
import { copyToClipboard } from "@/utils/copy";
import { downloadBlob } from "@/utils/download";
import { type Base64String, base64ToDataURL } from "@/utils/json/base64";
import type { FilePath } from "@/utils/paths";
import { makeDuplicateName } from "@/utils/pathUtils";
import { PYTHON_CODE_FOR_FILE_TYPE } from "@/components/editor/file-tree/types";
import { GitChangedFilesContext, RequestingTreeContext } from "./contexts";
import { FolderArrow } from "./FolderArrow";
import { Show } from "./Show";
import { openSpNotebook } from "./openSpNotebook";

export const Node = ({ node, style, dragHandle }: NodeRendererProps<FileInfo>) => {
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
