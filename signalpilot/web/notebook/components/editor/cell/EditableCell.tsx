import type { EditorView } from "@codemirror/view";
import clsx from "clsx";
import { useAtomValue } from "jotai";
import {
  HelpCircleIcon,
  SquareFunctionIcon,
} from "lucide-react";
import {
  useCallback,
  useRef,
  useState,
} from "react";
import { outputIsLoading, outputIsStale } from "@/core/cells/cell";
import { useCellActions, useCellData, useCellRuntime } from "@/core/cells/cells";
import type { CellId } from "@/core/cells/ids";
import { isOutputEmpty } from "@/core/cells/outputs";
import { useIsPendingCut } from "@/core/cells/pending-cut-service";
import type { LanguageAdapterType } from "@/core/codemirror/language/types";
import { CSSClasses } from "@/core/constants";
import { canCollapseOutline } from "@/core/dom/outline";
import { isErrorMime } from "@/core/mime";
import { connectionAtom } from "@/core/network/connection";
import { useRequestClient } from "@/core/network/requests";
import {
  cellNeedsRun,
  cellStatusClasses,
  isUninstantiated,
} from "@/core/cells/utils";
import { isAppInteractionDisabled } from "@/core/websocket/connection-utils";
import { useResizeObserver } from "@/hooks/useResizeObserver";
import { Tooltip, TooltipProvider } from "@/components/ui/tooltip";
import { cn } from "@/utils/cn";
import type { CellActionsDropdownHandle } from "./cell-actions";
import { CellActionsContextMenu } from "./cell-context-menu";
import { CellEditor } from "./code/cell-editor";
import { CollapsedCellBanner, CollapseToggle } from "./collapse";
import { DeleteButton } from "./DeleteButton";
import { PendingDeleteConfirmation } from "./PendingDeleteConfirmation";
import { useDeleteCellCallback } from "./useDeleteCell";
import { useRunCell } from "./useRunCells";
import { useCellCompletion, useCellHiddenLogic } from "./cell-hooks";
import type { CellProps } from "./cell-types";
import { CellLeftSideActions } from "./CellLeftSideActions";
import { CellRightSideActions } from "./CellRightSideActions";
import { CellToolbar } from "./CellToolbar";
import { cellDomProps } from "../common";
import { SqlValidationErrorBanner } from "../errors/sql-validation-errors";
import { useCellNavigationProps } from "../navigation/navigation";
import { OutputArea } from "../Output";
import { ConsoleOutput } from "../output/console/ConsoleOutput";
import { SortableCell } from "../SortableCell";

export const EditableCellComponent = ({
  theme,
  showPlaceholder,
  cellId,
  canDelete,
  userConfig,
  isCollapsed,
  collapseCount,
  canMoveX,
  editorView,
  setEditorView,
}: CellProps & {
  editorView: React.RefObject<EditorView | null>;
  setEditorView: (view: EditorView) => void;
}) => {
  const cellRef = useRef<HTMLDivElement>(null);
  const cellData = useCellData(cellId);
  const cellRuntime = useCellRuntime(cellId);
  const cellActionDropdownRef = useRef<CellActionsDropdownHandle>(null);
  // DOM node where the editorView will be mounted
  const editorViewParentRef = useRef<HTMLDivElement>(null);
  const cellContainerRef = useRef<HTMLDivElement>(null);

  const actions = useCellActions();
  const connection = useAtomValue(connectionAtom);
  const deleteCell = useDeleteCellCallback();
  const runCell = useRunCell(cellId);
  const { sendStdin } = useRequestClient();
  const isPendingCut = useIsPendingCut(cellId);

  const [languageAdapter, setLanguageAdapter] = useState<LanguageAdapterType>();

  const uninstantiated = isUninstantiated({
    executionTime: cellRuntime.runElapsedTimeMs ?? cellData.lastExecutionTime,
    status: cellRuntime.status,
    errored: cellRuntime.errored,
    interrupted: cellRuntime.interrupted,
    stopped: cellRuntime.stopped,
  });

  const needsRun = cellNeedsRun({
    edited: cellData.edited,
    interrupted: cellRuntime.interrupted,
    staleInputs: cellRuntime.staleInputs,
    disabled: cellData.config.disabled,
    status: cellRuntime.status,
  });

  const loading = outputIsLoading(cellRuntime.status);

  // console output is cleared immediately on run, so check for queued instead
  // of loading to determine staleness
  const consoleOutputStale =
    (cellRuntime.status === "queued" ||
      cellData.edited ||
      cellRuntime.staleInputs) &&
    !cellRuntime.interrupted;

  // Callback to get the editor view.
  const getEditorView = useCallback(() => editorView.current, [editorView]);

  // Use the extracted hooks
  const { closeCompletionHandler, resumeCompletionHandler } = useCellCompletion(
    cellRef,
    editorView,
  );

  const {
    isCellCodeShown,
    isMarkdown,
    isMarkdownCodeHidden,
    showHiddenCode,
    showHiddenCodeIfMarkdown,
  } = useCellHiddenLogic({
    cellId,
    cellConfig: cellData.config,
    languageAdapter,
    editorView,
    editorViewParentRef,
  });

  // Hotkey and focus props
  const navigationProps = useCellNavigationProps(cellId, {
    canMoveX,
    editorView,
    cellActionDropdownRef,
  });
  const canCollapse = canCollapseOutline(cellRuntime.outline);
  const hasOutput = !isOutputEmpty(cellRuntime.output);
  const isStaleCell = outputIsStale(cellRuntime, cellData.edited);
  const hasConsoleOutput = cellRuntime.consoleOutputs.length > 0;
  const cellOutput = userConfig.display.cell_output;

  const hasOutputAbove = hasOutput && cellOutput === "above";

  // If the cell is too short, we need to position some icons inline to prevent overlaps.
  // This can only happen to markdown cells when the code is hidden completely
  const [isCellStatusInline, setIsCellStatusInline] = useState(false);
  const [isCellButtonsInline, setIsCellButtonsInline] = useState(false);

  // For markdown cells, get the inner content directly from the editor
  // (editorView.state.doc contains the transformed markdown, not the sp.md(...) wrapper)
  const isEmptyMarkdownContent =
    isMarkdown && editorView.current?.state.doc.toString().trim() === "";

  useResizeObserver({
    ref: cellContainerRef,
    skip: !isMarkdown,
    onResize: (size) => {
      const cellTooShort = size.height && size.height < 68;
      const shouldBeInline =
        isMarkdownCodeHidden && (cellTooShort || cellOutput === "below");
      setIsCellStatusInline(shouldBeInline);

      if (canCollapse && shouldBeInline) {
        setIsCellButtonsInline(true);
      } else if (isCellButtonsInline) {
        setIsCellButtonsInline(false);
      }
    },
  });

  const emptyMarkdownPlaceholder = isMarkdownCodeHidden &&
    isEmptyMarkdownContent &&
    !needsRun && (
      <div
        role="button"
        aria-label="Double-click to edit markdown"
        className="relative cursor-pointer px-3 py-2"
        onDoubleClick={showHiddenCodeIfMarkdown}
        onKeyDown={(e) => {
          if (e.key === "Enter") {
            showHiddenCodeIfMarkdown();
          }
        }}
        tabIndex={0}
      >
        <span className="text-(--slate-8) text-sm">
          Double-click (or enter) to edit
        </span>
      </div>
    );

  const outputArea = hasOutput && !isEmptyMarkdownContent && (
    <div className="relative" onDoubleClick={showHiddenCodeIfMarkdown}>
      <div className="absolute top-5 -left-7 z-20 print:hidden">
        <CollapseToggle
          isCollapsed={isCollapsed}
          onClick={() => {
            if (isCollapsed) {
              actions.expandCell({ cellId });
            } else {
              actions.collapseCell({ cellId });
            }
          }}
          canCollapse={canCollapse}
        />
      </div>
      <OutputArea
        // Only allow expanding in edit mode
        allowExpand={true}
        // Force expand when markdown is hidden
        forceExpand={isMarkdownCodeHidden}
        className={CSSClasses.outputArea}
        cellId={cellId}
        output={cellRuntime.output}
        stale={isStaleCell}
        loading={outputIsLoading(cellRuntime.status)}
      />
    </div>
  );

  const className = clsx("sp-cell", "hover-actions-parent z-10", {
    interactive: true,
    ...cellStatusClasses({
      needsRun,
      errored: cellRuntime.errored,
      stopped: cellRuntime.stopped,
      disabled: cellData.config.disabled,
      status: cellRuntime.status,
    }),
    borderless:
      isMarkdownCodeHidden && hasOutput && !navigationProps["data-selected"],
    "pending-cut": isPendingCut,
  });

  // TODO(akshayka): Move to our own Tooltip component once it's easier
  // to get the tooltip to show next to the cursor ...
  // https://github.com/radix-ui/primitives/discussions/1090
  const renderCellTitle = () => {
    if (cellData.config.disabled) {
      return "This cell is disabled";
    }
    if (cellRuntime.status === "disabled-transitively") {
      return "This cell has a disabled ancestor";
    }
    return undefined;
  };

  const isToplevel = cellRuntime.serialization?.toLowerCase() === "valid";

  return (
    <TooltipProvider>
      <CellActionsContextMenu cellId={cellId} getEditorView={getEditorView}>
        <SortableCell
          tabIndex={-1}
          ref={cellRef}
          data-status={cellRuntime.status}
          onBlur={closeCompletionHandler}
          onKeyDown={resumeCompletionHandler}
          cellId={cellId}
          canMoveX={canMoveX}
          title={renderCellTitle()}
        >
          <div
            tabIndex={-1}
            {...navigationProps}
            className={cn(
              className,
              navigationProps.className,
              "focus:ring-1 focus:ring-(--slate-8) focus:ring-offset-2",
            )}
            ref={cellContainerRef}
            {...cellDomProps(cellId, cellData.name)}
          >
            <CellLeftSideActions cellId={cellId} actions={actions} />
            {cellOutput === "above" && (outputArea || emptyMarkdownPlaceholder)}
            <div
              className={cn("tray")}
              data-has-output-above={hasOutputAbove}
              data-hidden={isMarkdownCodeHidden}
            >
              <div className="absolute right-2 -top-4 z-10">
                <CellToolbar
                  edited={cellData.edited}
                  status={cellRuntime.status}
                  cellConfig={cellData.config}
                  needsRun={needsRun}
                  hasOutput={hasOutput}
                  hasConsoleOutput={hasConsoleOutput}
                  cellActionDropdownRef={cellActionDropdownRef}
                  cellId={cellId}
                  name={cellData.name}
                  getEditorView={getEditorView}
                  onRun={runCell}
                />
              </div>
              <CellEditor
                theme={theme}
                showPlaceholder={showPlaceholder}
                id={cellId}
                code={cellData.code}
                config={cellData.config}
                status={cellRuntime.status}
                serializedEditorState={cellData.serializedEditorState}
                runCell={runCell}
                setEditorView={setEditorView}
                userConfig={userConfig}
                editorViewRef={editorView}
                editorViewParentRef={editorViewParentRef}
                hidden={!isCellCodeShown}
                hasOutput={hasOutput}
                showHiddenCode={showHiddenCode}
                languageAdapter={languageAdapter}
                setLanguageAdapter={setLanguageAdapter}
                outputArea={cellOutput}
              />
              <CellRightSideActions
                className={cn(
                  isMarkdownCodeHidden && cellOutput === "below" && "top-14",
                )}
                edited={cellData.edited}
                status={cellRuntime.status}
                isCellStatusInline={isCellStatusInline}
                uninstantiated={uninstantiated}
                disabled={cellData.config.disabled}
                runElapsedTimeMs={cellRuntime.runElapsedTimeMs}
                runStartTimestamp={cellRuntime.runStartTimestamp}
                lastRunStartTimestamp={cellRuntime.lastRunStartTimestamp}
                staleInputs={cellRuntime.staleInputs}
                interrupted={cellRuntime.interrupted}
              />
              <div className="shoulder-bottom hover-action">
                {canDelete && isCellCodeShown && (
                  <DeleteButton
                    status={cellRuntime.status}
                    connectionState={connection.state}
                    onClick={() => {
                      if (
                        !loading &&
                        !isAppInteractionDisabled(connection.state)
                      ) {
                        deleteCell({ cellId });
                      }
                    }}
                  />
                )}
              </div>
            </div>
            <SqlValidationErrorBanner
              cellId={cellId}
              hide={cellRuntime.errored && !isStaleCell}
            />
            {cellOutput === "below" && (outputArea || emptyMarkdownPlaceholder)}
            {cellRuntime.serialization && (
              <div className="py-1 px-2 flex items-center justify-end gap-2 last:rounded-b">
                {isToplevel && (
                  <a
                    href="https://docs.signalpilot.ai/docs/"
                    target="_blank"
                    className="hover:underline text-muted-foreground text-xs font-bold"
                    rel="noopener"
                  >
                    reusable
                  </a>
                )}
                <Tooltip
                  content={
                    <span className="max-w-16 text-xs">
                      {(isToplevel &&
                        "This function or class can be imported into other Python notebooks or modules.") || (
                        <>
                          This definition can't be reused in other Python
                          modules:
                          <br />
                          <br />
                          <pre>{cellRuntime.serialization}</pre>
                          <br />
                          Click this icon to learn more.
                        </>
                      )}
                    </span>
                  }
                >
                  {isToplevel ? (
                    <a
                      href="https://docs.signalpilot.ai/docs/"
                      target="_blank"
                      rel="noreferrer"
                    >
                      <SquareFunctionIcon
                        size={16}
                        strokeWidth={1.5}
                        className="rounded-lg text-muted-foreground"
                      />
                    </a>
                  ) : (
                    <a
                      href="https://docs.signalpilot.ai/docs/"
                      target="_blank"
                      rel="noopener"
                    >
                      <HelpCircleIcon
                        size={16}
                        strokeWidth={1.5}
                        className="rounded-lg text-muted-foreground"
                      />
                    </a>
                  )}
                </Tooltip>
              </div>
            )}
            <ConsoleOutput
              consoleOutputs={cellRuntime.consoleOutputs}
              stale={consoleOutputStale}
              // Empty name if serialization triggered
              cellName={cellRuntime.serialization ? "_" : cellData.name}
              onClear={() => {
                actions.clearCellConsoleOutput({ cellId });
              }}
              onSubmitDebugger={(text, index) => {
                actions.setStdinResponse({
                  cellId,
                  response: text,
                  outputIndex: index,
                });
                sendStdin({ text });
              }}
              cellId={cellId}
              debuggerActive={cellRuntime.debuggerActive}
            />
            <PendingDeleteConfirmation cellId={cellId} />
          </div>
          {isCollapsed && (
            <CollapsedCellBanner
              onClick={() => actions.expandCell({ cellId })}
              count={collapseCount}
              cellId={cellId}
            />
          )}
        </SortableCell>
      </CellActionsContextMenu>
    </TooltipProvider>
  );
};
