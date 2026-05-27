import { closeCompletion, completionStatus } from "@codemirror/autocomplete";
import type { EditorView } from "@codemirror/view";
import { useAtomValue } from "jotai";
import { type FocusEvent, type KeyboardEvent, useMemo } from "react";
import useEvent from "react-use-event-hook";
import { autocompletionKeymap } from "@/core/codemirror/cm";
import { createUntouchedCellAtom } from "@/core/cells/cells";
import type { CellId } from "@/core/cells/ids";
import type { CellConfig } from "@/core/network/types";
import type { LanguageAdapterType } from "@/core/codemirror/language/types";
import {
  useTemporarilyShownCode,
  useTemporarilyShownCodeActions,
} from "../navigation/state";

/**
 * Hook for handling cell completion logic
 */
export function useCellCompletion(
  cellRef: React.RefObject<HTMLDivElement | null>,
  editorView: React.RefObject<EditorView | null>,
) {
  // Close completion when focus leaves the cell's subtree.
  const closeCompletionHandler = useEvent((e: FocusEvent) => {
    if (
      cellRef.current !== null &&
      !cellRef.current.contains(e.relatedTarget) &&
      editorView.current !== null
    ) {
      closeCompletion(editorView.current);
    }
  });

  // Clicking on the completion info causes the editor view to lose focus,
  // because the completion is not a child of the editable editor DOM;
  // as a workaround, when a completion is active, we refocus the editor
  // on any keypress.
  //
  // See https://discuss.codemirror.net/t/adding-click-event-listener-to-autocomplete-tooltip-info-panel-is-not-working/4741
  const resumeCompletionHandler = useEvent((e: KeyboardEvent) => {
    if (
      cellRef.current !== document.activeElement ||
      editorView.current === null ||
      completionStatus(editorView.current.state) !== "active"
    ) {
      return;
    }

    for (const keymap of autocompletionKeymap) {
      if (e.key === keymap.key && keymap.run) {
        keymap.run(editorView.current);
        // preventDefault/stopPropagation: Don't process the keystrokes as
        // typing into the editor, e.g., Enter should only select the
        // completion, not also add a newline.
        e.preventDefault();
        e.stopPropagation();
        break;
      }
    }
    editorView.current.focus();
    return;
  });

  return {
    closeCompletionHandler,
    resumeCompletionHandler,
  };
}

/**
 * Hook for handling hidden cell logic.
 *
 * The code is shown if:
 * - hide_code is false
 * - the cell-editor is focused (temporarily shown)
 * - the cell is newly created (untouched)
 */
export function useCellHiddenLogic({
  cellId,
  cellConfig,
  languageAdapter,
  editorView,
}: {
  cellId: CellId;
  cellConfig: CellConfig;
  languageAdapter: LanguageAdapterType | undefined;
  editorView: React.RefObject<EditorView | null>;
  editorViewParentRef: React.RefObject<HTMLDivElement | null>;
}) {
  const temporarilyVisible = useTemporarilyShownCode(cellId);
  const temporarilyShownCodeActions = useTemporarilyShownCodeActions();
  const isUntouched = useAtomValue(
    useMemo(() => createUntouchedCellAtom(cellId), [cellId]),
  );

  // The cell code is shown if the cell is not configured to be hidden or if the code is temporarily visible (i.e. when focused).
  const isCellCodeShown =
    !cellConfig.hide_code || temporarilyVisible || isUntouched;
  const isMarkdown = languageAdapter === "markdown";
  const isMarkdownCodeHidden = isMarkdown && !isCellCodeShown;

  // Callback to show the code editor temporarily
  const showHiddenCode = useEvent((opts?: { focus?: boolean }) => {
    // Already shown, do nothing
    if (isCellCodeShown) {
      return;
    }

    // Default to true
    const focus = opts?.focus ?? true;
    temporarilyShownCodeActions.add(cellId);

    if (focus) {
      editorView.current?.focus();
    }

    // Undoing happens in editor/focus/focus.ts, when the cell is blurred.
  });

  const showHiddenCodeIfMarkdown = useEvent(() => {
    if (isMarkdownCodeHidden) {
      showHiddenCode({ focus: true });
    }
  });

  return {
    isCellCodeShown,
    isMarkdown,
    isMarkdownCodeHidden,
    showHiddenCode,
    showHiddenCodeIfMarkdown,
  };
}
