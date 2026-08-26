import type { NodeApi } from "react-arborist";
import type { FileInfo } from "@/core/network/types";
import { TreeChevron } from "@/components/editor/file-tree/tree-actions";

export const FolderArrow = ({ node }: { node: NodeApi<FileInfo> }) => {
  if (!node.data.isDirectory) {
    return <span className="w-4 h-4 shrink-0" />;
  }

  return <TreeChevron isExpanded={node.isOpen} className="w-4 h-4" />;
};
