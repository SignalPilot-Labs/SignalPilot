import React from "react";
import useResizeObserver from "use-resize-observer";
import { cn } from "@/utils/cn";
import { TreeDndProvider } from "../../file-tree/dnd-wrapper";
import { FileExplorer } from "../../file-tree/file-explorer";
import { useFileExplorerUpload } from "../../file-tree/upload";

const FileExplorerPanel: React.FC = () => {
  const { ref: panelRef, height: panelHeight = 500 } =
    useResizeObserver<HTMLDivElement>();
  const { getRootProps, getInputProps, isDragActive } = useFileExplorerUpload({
    noClick: true,
    noKeyboard: true,
  });

  return (
    <div ref={panelRef} className="h-full overflow-auto">
      <TreeDndProvider>
        <div
          {...getRootProps()}
          className={cn("flex flex-col overflow-hidden relative")}
          style={{ height: panelHeight }}
        >
          <input {...getInputProps()} />
          {isDragActive && (
            <div className="absolute inset-0 flex items-center uppercase justify-center text-xl font-bold text-primary/90 bg-accent/85 z-10 border-2 border-dashed border-primary/90 pointer-events-none">
              Drop files here
            </div>
          )}
          <FileExplorer height={panelHeight} />
        </div>
      </TreeDndProvider>
    </div>
  );
};

export default FileExplorerPanel;
