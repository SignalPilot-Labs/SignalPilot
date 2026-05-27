import type { EditorView } from "@codemirror/view";
import clsx from "clsx";
import { useAtomValue } from "jotai";
import { HelpCircleIcon } from "lucide-react";
import { useCallback, useRef } from "react";
import { mergeProps } from "react-aria";
import { outputIsLoading } from "@/core/cells/cell";
import { useCellActions, useCellData, useCellRuntime } from "@/core/cells/cells";
import type { CellId } from "@/core/cells/ids";
import { isOutputEmpty } from "@/core/cells/outputs";
import { CSSClasses } from "@/core/constants";
import { isErrorMime } from "@/core/mime";
import { connectionAtom } from "@/core/network/connection";
import { useRequestClient } from "@/core/network/requests";
import {
  cellNeedsRun,
  cellStatusClasses,
  isUninstantiated,
} from "@/core/cells/utils";
import { isAppInteractionDisabled } from "@/core/websocket/connection-utils";
import { Tooltip, TooltipProvider } from "@/components/ui/tooltip";
import { cn } from "@/utils/cn";
import { Functions } from "@/utils/functions";
import type { CellActionsDropdownHandle } from "./cell-actions";
import { CellActionsContextMenu } from "./cell-context-menu";
import { CellEditor } from "./code/cell-editor";
import { DeleteButton } from "./DeleteButton";
import { useDeleteCellCallback } from "./useDeleteCell";
import { useRunCell } from "./useRunCells";
import { useCellCompletion, useCellHiddenLogic } from "./cell-hooks";
import type { CellProps } from "./cell-types";
import { CellRightSideActions } from "./CellRightSideActions";
import { CellToolbar } from "./CellToolbar";
import { cellDomProps } from "../common";
import { useCellNavigationProps } from "../navigation/navigation";
import { OutputArea } from "../Output";
import { ConsoleOutput } from "../output/console/ConsoleOutput";

/**
 * A cell that is not allowed to be deleted or moved.
 * It also has no outputs.
 */
export const SetupCellComponent = ({
  theme,
  showPlaceholder,
  cellId,
  canDelete,
  userConfig,
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
  const connection = useAtomValue(connectionAtom);

  const actions = useCellActions();
  const requestClient = useRequestClient();
  const deleteCell = useDeleteCellCallback();
  const runCell = useRunCell(cellId);

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
  const loading =
    cellRuntime.status === "running" || cellRuntime.status === "queued";

  // console output is cleared immediately on run, so check for queued instead
  // of loading to determine staleness
  const consoleOutputStale =
    (cellRuntime.status === "queued" ||
      cellData.edited ||
      cellRuntime.staleInputs) &&
    !cellRuntime.interrupted;

  // Callback to get the editor view.
  const getEditorView = useCallback(() => editorView.current, [editorView]);

  const { isCellCodeShown, showHiddenCode } = useCellHiddenLogic({
    cellId,
    cellConfig: cellData.config,
    languageAdapter: "python",
    editorView,
    editorViewParentRef,
  });

  // Use the extracted hooks
  const { closeCompletionHandler, resumeCompletionHandler } = useCellCompletion(
    cellRef,
    editorView,
  );

  // Hotkeys and focus props
  const navigationProps = useCellNavigationProps(cellId, {
    canMoveX,
    editorView,
    cellActionDropdownRef,
  });
  const hasOutput = !isOutputEmpty(cellRuntime.output);
  const hasConsoleOutput = cellRuntime.consoleOutputs.length > 0;
  const isErrorOutput = isErrorMime(cellRuntime.output?.mimetype);

  const className = clsx("sp-cell", "hover-actions-parent z-10", {
    interactive: true,
    ...cellStatusClasses({
      needsRun,
      errored: cellRuntime.errored,
      stopped: cellRuntime.stopped,
      disabled: cellData.config.disabled,
      status: cellRuntime.status,
    }),
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

  return (
    <TooltipProvider>
      <CellActionsContextMenu cellId={cellId} getEditorView={getEditorView}>
        <div>
          <div
            data-status={cellRuntime.status}
            ref={cellRef}
            {...mergeProps(navigationProps, {
              className: cn(
                className,
                "focus:ring-1 focus:ring-(--slate-8) focus:ring-offset-2",
              ),
              onBlur: closeCompletionHandler,
              onKeyDown: resumeCompletionHandler,
            })}
            {...cellDomProps(cellId, cellData.name)}
            title={renderCellTitle()}
            tabIndex={-1}
            data-setup-cell={true}
          >
            <div
              className={cn("tray")}
              data-has-output-above={false}
              data-hidden={!isCellCodeShown}
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
                  includeCellActions={true}
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
                languageAdapter={"python"}
                setLanguageAdapter={Functions.NOOP}
                showLanguageToggles={false}
              />
              <CellRightSideActions
                edited={cellData.edited}
                status={cellRuntime.status}
                isCellStatusInline={false}
                uninstantiated={uninstantiated}
                disabled={cellData.config.disabled}
                runElapsedTimeMs={cellRuntime.runElapsedTimeMs}
                runStartTimestamp={cellRuntime.runStartTimestamp}
                lastRunStartTimestamp={cellRuntime.lastRunStartTimestamp}
                staleInputs={cellRuntime.staleInputs}
                interrupted={cellRuntime.interrupted}
              />
              <div className="shoulder-bottom hover-action">
                {canDelete && (
                  <DeleteButton
                    connectionState={connection.state}
                    status={cellRuntime.status}
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
            <div className="py-1 px-2 flex justify-end gap-2 last:rounded-b">
              <span className="text-muted-foreground text-xs font-bold">
                setup cell
              </span>
              <Tooltip
                content={
                  <span className="max-w-16">
                    This <b>setup cell</b> is guaranteed to run before all other
                    cells. Include <br />
                    initialization or imports and constants required by
                    top-level functions.
                  </span>
                }
              >
                <HelpCircleIcon
                  size={16}
                  strokeWidth={1.5}
                  className="rounded-lg text-muted-foreground"
                />
              </Tooltip>
            </div>
            {isErrorOutput && (
              <OutputArea
                allowExpand={true}
                forceExpand={true}
                className={CSSClasses.outputArea}
                cellId={cellId}
                output={cellRuntime.output}
                stale={false}
                loading={loading}
              />
            )}
            <ConsoleOutput
              consoleOutputs={cellRuntime.consoleOutputs}
              stale={consoleOutputStale}
              // Don't show name
              cellName={"_"}
              onClear={() => {
                actions.clearCellConsoleOutput({ cellId });
              }}
              onSubmitDebugger={(text, index) => {
                actions.setStdinResponse({
                  cellId,
                  response: text,
                  outputIndex: index,
                });
                requestClient.sendStdin({ text });
              }}
              cellId={cellId}
              debuggerActive={cellRuntime.debuggerActive}
            />
          </div>
        </div>
      </CellActionsContextMenu>
    </TooltipProvider>
  );
};
