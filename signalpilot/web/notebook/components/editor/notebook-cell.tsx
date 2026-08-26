import type { EditorView } from "@codemirror/view";
import { memo, useImperativeHandle, useRef } from "react";
import { useCellHandle } from "@/core/cells/cells";
import { SETUP_CELL_ID } from "@/core/cells/ids";
import { useCellRenderCount } from "@/hooks/useCellRenderCount";
import { Logger } from "@/utils/Logger";
import { EditableCellComponent } from "./cell/EditableCell";
import { ReadonlyCellComponent } from "./cell/ReadonlyCell";
import { SetupCellComponent } from "./cell/SetupCell";
import type { CellProps } from "./cell/cell-types";

export type { CellHandle } from "./cell/cell-types";

const CellComponent = (props: CellProps) => {
  const { cellId, mode } = props;
  const ref = useCellHandle(cellId);

  useCellRenderCount().countRender();

  Logger.debug("Rendering Cell", cellId);

  const editorView = useRef<EditorView | null>(null);

  // An imperative interface to the code editor
  useImperativeHandle(
    ref,
    () => ({
      get editorView() {
        if (editorView.current === null) {
          return null as unknown as EditorView;
        }
        return editorView.current;
      },
      get editorViewOrNull() {
        return editorView.current;
      },
    }),
    [editorView],
  );

  if (cellId === SETUP_CELL_ID) {
    return (
      <SetupCellComponent
        {...props}
        cellId={cellId}
        editorView={editorView}
        setEditorView={(ev) => {
          editorView.current = ev;
        }}
      />
    );
  }

  if (mode === "edit") {
    return (
      <EditableCellComponent
        {...props}
        cellId={cellId}
        editorView={editorView}
        setEditorView={(ev) => {
          editorView.current = ev;
        }}
      />
    );
  }

  return <ReadonlyCellComponent cellId={cellId} />;
};

export const Cell = memo(CellComponent);
