import type { EditorView } from "@codemirror/view";
import type { CellActions } from "@/core/cells/cells";
import type { CellId } from "@/core/cells/ids";
import type { UserConfig } from "@/core/config/config-schema";
import type { AppMode } from "@/core/mode";
import type { Theme } from "@/theme/useTheme";

export type CellComponentActions = Pick<
  CellActions,
  | "updateCellCode"
  | "createNewCell"
  | "focusCell"
  | "moveCell"
  | "collapseCell"
  | "expandCell"
  | "moveToNextCell"
  | "updateCellConfig"
  | "clearSerializedEditorState"
  | "setStdinResponse"
  | "clearCellConsoleOutput"
  | "sendToBottom"
  | "sendToTop"
>;

/**
 * Imperative interface of the cell.
 */
export interface CellHandle {
  /**
   * The CodeMirror editor view.
   */
  editorView: EditorView;
  /**
   * The CodeMirror editor view, or null if it is not yet mounted.
   */
  editorViewOrNull: EditorView | null;
}

export interface CellProps {
  cellId: CellId;
  theme: Theme;
  showPlaceholder: boolean;
  mode: AppMode;
  /**
   * False only when there is only one cell in the notebook.
   */
  canDelete: boolean;
  userConfig: UserConfig;
  /**
   * If true, the cell is allowed to be moved left and right.
   */
  canMoveX: boolean;
  /**
   * If true, the cell is collapsed.
   */
  isCollapsed: boolean;
  /**
   * The number of cells in the column.
   */
  collapseCount: number;
}
