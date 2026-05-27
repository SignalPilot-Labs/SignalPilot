import { useAtom, useAtomValue } from "jotai";
import { spApiUrl } from "@/core/network/api";
import { isConnectedAtom } from "@/core/network/connection";
import { classifyFile } from "@/core/active-file";
import { openFileInTab } from "@/core/file-tabs";
import {
  ArrowLeftIcon,
} from "lucide-react";
import React, { Suspense, useRef, useState } from "react";
import useResizeObserver from "use-resize-observer";
import {
  type TreeApi,
  Tree,
} from "react-arborist";
import useEvent from "react-use-event-hook";
import { Button } from "@/components/ui/button";
import { Spinner } from "@/components/icons/spinner";
import { useImperativeModal } from "@/components/modal/ImperativeModal";
import { getGatewayProjectId } from "@/core/network/api";
import { getApiHeaders } from "@/core/network/api-headers";
import { useAsyncData } from "@/hooks/useAsyncData";
import { ErrorBanner } from "@/plugins/impl/common/error-banner";
import { openNotebook } from "@/utils/links";
import type { FilePath } from "@/utils/paths";
import type { FileInfo } from "@/core/network/types";
import { useTreeDndManager } from "./dnd-wrapper";
import { FileViewer } from "./file-viewer";
import { openStateAtom, treeAtom } from "./state";
import { GitChangedFilesContext, RequestingTreeContext } from "./file-explorer/contexts";
import { hiddenFilesState, filterHiddenTree } from "./file-explorer/hidden-files";
import { Toolbar } from "./file-explorer/Toolbar";
import { CloudSyncBar } from "./file-explorer/CloudSyncBar";
import { Node } from "./file-explorer/Node";
import { openSpNotebook } from "./file-explorer/openSpNotebook";

export { filterHiddenTree, isDirectoryOrFileHidden } from "./file-explorer/hidden-files";

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
          indent={15}
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
