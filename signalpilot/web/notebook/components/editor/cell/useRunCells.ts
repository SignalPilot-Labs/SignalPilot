import { closeCompletion } from "@codemirror/autocomplete";
import { atom, useSetAtom } from "jotai";
import useEvent from "react-use-event-hook";
import {
  getNotebook,
  type NotebookState,
  useCellActions,
} from "@/core/cells/cells";
import type { CellId } from "@/core/cells/ids";
import { enabledCellIds, staleCellIds } from "@/core/cells/utils";
import { getCurrentLanguageAdapter } from "@/core/codemirror/language/commands";
import { getEditorCodeAsPython } from "@/core/codemirror/language/utils";
import { useRequestClient } from "@/core/network/requests";
import type { ExecuteCellsRequest } from "@/core/network/types";
import { Logger } from "@/utils/Logger";

export const hasRunAnyCellAtom = atom<boolean>(false);

/**
 * Creates a function that runs all cells that have been edited or interrupted.
 */
export function useRunStaleCells() {
  const runCells = useRunCells();
  const runStaleCells = useEvent(() => runCells(staleCellIds(getNotebook())));
  return runStaleCells;
}

/**
 * Creates a function that runs the cell with the given id.
 */
export function useRunCell(cellId: CellId | undefined) {
  const runCells = useRunCells();
  const runCell = useEvent(() => {
    if (cellId === undefined) {
      return;
    }
    runCells([cellId]);
  });
  return runCell;
}

export function useRunAllCells() {
  const runCells = useRunCells();
  const runAllCells = useEvent(() => runCells(enabledCellIds(getNotebook())));
  return runAllCells;
}

/**
 * Creates a function that runs the given cells.
 */
export function useRunCells() {
  const { prepareForRun } = useCellActions();
  const { sendRun } = useRequestClient();
  const setHasRunAnyCell = useSetAtom(hasRunAnyCellAtom);

  const runCellsMemoized = useEvent(async (cellIds: CellId[]) => {
    if (cellIds.length === 0) {
      return;
    }

    const notebook = getNotebook();

    // Set a flag that a user has manually run at least one cell.
    setHasRunAnyCell(true);

    return runCells({ cellIds, sendRun, prepareForRun, notebook });
  });

  return runCellsMemoized;
}

export async function runCells({
  cellIds,
  sendRun,
  prepareForRun,
  notebook,
}: {
  cellIds: CellId[];
  sendRun: (request: ExecuteCellsRequest) => Promise<null>;
  prepareForRun: (action: { cellId: CellId }) => void;
  notebook: NotebookState;
}) {
  if (cellIds.length === 0) {
    return;
  }

  // Lazy runtime with no kernel yet (sessionless boot): the first Run is
  // what provisions the sandbox. A fresh kernel re-ids every cell at
  // kernel-ready, so ids captured now would be dead on arrival — connect
  // FIRST, then remap the requested cells by position and rebuild the
  // payload from the reconciled notebook state.
  const [
    { getRuntimeManager, connectToRuntimeAndWaitReady },
    { store },
    { connectionAtom },
    { WebSocketState },
    { kernelLaunchAtom, isKernelLaunchInFlight },
  ] = await Promise.all([
    import("@/core/runtime/config"),
    import("@/core/state/jotai"),
    import("@/core/network/connection"),
    import("@/core/websocket/types"),
    import("@/core/runtime/launch-state"),
  ]);
  if (
    getRuntimeManager().isLazy &&
    (store.get(connectionAtom).state !== WebSocketState.OPEN ||
      // Socket open but the kernel is still coming up (it re-ids every cell
      // at kernel-ready) — wait and remap rather than firing dead ids.
      isKernelLaunchInFlight(store.get(kernelLaunchAtom)))
  ) {
    const positions = cellIds.map((id) =>
      notebook.cellIds.inOrderIds.indexOf(id),
    );
    try {
      await connectToRuntimeAndWaitReady();
    } catch (error) {
      Logger.error("Failed to start the notebook runtime", error);
      const { toast } = await import("@/components/ui/use-toast");
      toast({
        title: "Failed to start the notebook runtime",
        description: error instanceof Error ? error.message : String(error),
        variant: "danger",
      });
      return;
    }
    const freshNotebook = getNotebook();
    const freshIds = freshNotebook.cellIds.inOrderIds;
    const remapped = positions
      .map((i) => (i >= 0 ? freshIds[i] : undefined))
      .filter((id): id is CellId => id !== undefined);
    if (remapped.length === 0) {
      return;
    }
    cellIds = remapped;
    notebook = freshNotebook;
  }

  const { cellHandles, cellData } = notebook;

  const codes: string[] = [];
  for (const cellId of cellIds) {
    const ref = cellHandles[cellId];
    const ev = ref?.current?.editorView;
    let code: string;
    // Performs side-effects that must run whenever the cell is run, but doesn't
    // actually run the cell.
    if (ev) {
      // Skip close on markdown, since we autorun, otherwise we'll close the
      // completion each time.
      if (getCurrentLanguageAdapter(ev) !== "markdown") {
        closeCompletion(ev);
      }
      // Prefer code from editor
      code = getEditorCodeAsPython(ev);
    } else {
      code = cellData[cellId]?.code || "";
    }

    codes.push(code);
    prepareForRun({ cellId });
  }

  // Send the run request to the Kernel
  await sendRun({ cellIds: cellIds, codes: codes }).catch((error) => {
    Logger.error(error);
  });
}
