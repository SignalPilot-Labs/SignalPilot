import { EditorState } from "@codemirror/state";

/**
 * Check if the editor is currently readonly
 */
export function isEditorReadonly(state: EditorState): boolean {
  return state.facet(EditorState.readOnly);
}
