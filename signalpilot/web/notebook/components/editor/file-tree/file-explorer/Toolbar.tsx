import {
  CopyMinusIcon,
  EyeOffIcon,
  FilePlus2Icon,
  FolderPlusIcon,
  NotebookPenIcon,
  UploadIcon,
} from "lucide-react";
import { Button, buttonVariants } from "@/components/ui/button";
import { Tooltip } from "@/components/ui/tooltip";
import {
  RefreshIconButton,
} from "@/components/editor/file-tree/tree-actions";
import { useFileExplorerUpload } from "@/components/editor/file-tree/upload";
import type { RequestingTree } from "@/components/editor/file-tree/requesting-tree";

export interface ToolbarProps {
  onRefresh: () => void;
  onHidden: () => void;
  onCreateFile: () => void;
  onCreateNotebook: () => void;
  onCreateFolder: () => void;
  onCollapseAll: () => void;
  tree: RequestingTree;
}

export const Toolbar = ({
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
