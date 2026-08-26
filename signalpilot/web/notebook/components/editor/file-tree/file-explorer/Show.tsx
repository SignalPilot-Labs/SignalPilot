import { ExternalLinkIcon } from "lucide-react";
import type { NodeApi } from "react-arborist";
import type { FileInfo } from "@/core/network/types";

export const Show = ({
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
