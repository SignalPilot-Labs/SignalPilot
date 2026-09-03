import { useAtomValue } from "jotai";
import {
  Loader2Icon,
} from "lucide-react";
import type React from "react";
import { memo, useEffect, useRef, useState } from "react";
import { z } from "zod";
import { ReadonlyCode } from "@/components/editor/code/readonly-python-code";
import { OutputArea } from "@/components/editor/Output";
import { ConsoleOutput } from "@/components/editor/output/console/ConsoleOutput";
import { Alert, AlertDescription, AlertTitle } from "@/components/ui/alert";
import { outputIsLoading, outputIsStale } from "@/core/cells/cell";
import type { CellId } from "@/core/cells/ids";
import { isOutputEmpty } from "@/core/cells/outputs";
import type { CellData, CellRuntimeState } from "@/core/cells/types";
import { MarkdownLanguageAdapter } from "@/core/codemirror/language/languages/markdown";
import { useResolvedSpConfig } from "@/core/config/config";
import { CSSClasses, KnownQueryParams } from "@/core/constants";
import type { SpError, OutputMessage } from "@/core/kernel/messages";
import { kernelStateAtom } from "@/core/kernel/state";
import { useNotebookCodeAvailable } from "@/core/meta/code-visibility";
import { showCodeInRunModeAtom } from "@/core/meta/state";
import { isErrorMime } from "@/core/mime";
import { type AppMode, kioskModeAtom } from "@/core/mode";
import type { CellConfig } from "@/core/network/types";
import { isStaticNotebook } from "@/core/static/static-state";

import { cn } from "@/utils/cn";
import { FloatingOutline } from "../../chrome/panels/outline/floating-outline";
import { cellDomProps } from "../../common";
import type { ICellRendererPlugin, ICellRendererProps } from "../types";
import { NotebookActionButtons } from "./notebook-actions";
import { useDelayVisibility } from "./useDelayVisibility";
import { VerticalLayoutWrapper } from "./vertical-layout-wrapper";

type VerticalLayout = null;
type VerticalLayoutProps = ICellRendererProps<VerticalLayout>;

const VerticalLayoutRenderer: React.FC<VerticalLayoutProps> = ({
  cells,
  appConfig,
  mode,
}) => {
  const { invisible } = useDelayVisibility(cells.length, mode);
  const kioskMode = useAtomValue(kioskModeAtom);
  const kernelState = useAtomValue(kernelStateAtom);
  const [userConfig] = useResolvedSpConfig();
  const showCodeInRunModePreference = useAtomValue(showCodeInRunModeAtom);

  const urlParams = new URLSearchParams(window.location.search);
  const [showCode, setShowCode] = useState(() => {
    // Check if the setting was set in the mount options
    if (!showCodeInRunModePreference) {
      return false;
    }
    // If 'auto' or not found, use URL param
    // If url param is not set, we default to true for static notebooks, wasm notebooks, and kiosk mode
    const showCodeByQueryParam = urlParams.get(KnownQueryParams.showCode);
    return showCodeByQueryParam === null
      ? isStaticNotebook() || kioskMode
      : showCodeByQueryParam === "true";
  });

  // Follow later kiosk changes: viewer embeds flip the kiosk flag to switch
  // a mounted notebook between the code and app views. An explicit URL
  // override or a disabled run-mode preference still wins.
  useEffect(() => {
    if (!showCodeInRunModePreference) return;
    const byQueryParam = new URLSearchParams(window.location.search).get(
      KnownQueryParams.showCode,
    );
    if (byQueryParam !== null) return;
    setShowCode(isStaticNotebook() || kioskMode);
  }, [kioskMode, showCodeInRunModePreference]);

  const canShowCode = useNotebookCodeAvailable(cells);

  const renderCell = (cell: CellRuntimeState & CellData) => {
    return (
      <VerticalCell
        key={cell.id}
        cellId={cell.id}
        output={cell.output}
        consoleOutputs={cell.consoleOutputs}
        status={cell.status}
        code={cell.code}
        config={cell.config}
        cellOutputArea={userConfig.display.cell_output}
        stopped={cell.stopped}
        showCode={showCode && canShowCode}
        errored={cell.errored}
        mode={mode}
        runStartTimestamp={cell.runStartTimestamp}
        interrupted={cell.interrupted}
        staleInputs={cell.staleInputs}
        name={cell.name}
        kiosk={kioskMode}
        showErrorTracebacks={userConfig.runtime.show_tracebacks ?? false}
      />
    );
  };

  const renderCells = () => {
    if (appConfig.width === "columns") {
      const sortedColumns = groupCellsByColumn(cells);
      return (
        <div className="flex flex-row gap-8 w-full">
          {sortedColumns.map(([columnIndex, columnCells]) => (
            <div
              key={columnIndex}
              className="flex-1 flex flex-col gap-2 w-(--content-width)"
            >
              {columnCells.map(renderCell)}
            </div>
          ))}
        </div>
      );
    }

    if (cells.length === 0 && !invisible) {
      // If kernel is not yet instantiated, show loading state
      if (!kernelState.isInstantiated) {
        return (
          <div className="flex-1 flex flex-col items-center justify-center py-8">
            <Loader2Icon className="w-8 h-8 animate-spin text-muted-foreground" />
          </div>
        );
      }
      // Kernel is ready but no cells - truly empty notebook
      return (
        <div className="flex-1 flex flex-col items-center justify-center py-8">
          <Alert variant="info">
            <AlertTitle>Empty Notebook</AlertTitle>
            <AlertDescription>
              This notebook has no code or outputs.
            </AlertDescription>
          </Alert>
        </div>
      );
    }

    return <>{cells.map(renderCell)}</>;
  };

  // in read mode (required for canShowCode to be true), we need to insert
  // spacing between cells to prevent them from colliding; in edit mode,
  // spacing is handled elsewhere
  return (
    <VerticalLayoutWrapper invisible={invisible} appConfig={appConfig}>
      <div className={cn("flex flex-col", showCode && canShowCode && "gap-5")}>
        {renderCells()}
      </div>
      {mode === "read" && (
        <NotebookActionButtons
          canShowCode={canShowCode}
          showCode={showCode}
          onToggleShowCode={() => setShowCode((v) => !v)}
        />
      )}
      <FloatingOutline />
    </VerticalLayoutWrapper>
  );
};

interface VerticalCellProps extends Pick<
  CellRuntimeState,
  | "output"
  | "consoleOutputs"
  | "status"
  | "stopped"
  | "errored"
  | "interrupted"
  | "staleInputs"
  | "runStartTimestamp"
> {
  cellOutputArea: "above" | "below";
  cellId: CellId;
  config: CellConfig;
  code: string;
  mode: AppMode;
  showCode: boolean;
  name: string;
  kiosk: boolean;
  showErrorTracebacks: boolean;
}

const VerticalCell = memo(
  ({
    output,
    consoleOutputs,
    cellOutputArea,
    cellId,
    status,
    stopped,
    errored,
    config,
    interrupted,
    staleInputs,
    runStartTimestamp,
    code,
    showCode,
    mode,
    name,
    kiosk,
    showErrorTracebacks,
  }: VerticalCellProps) => {
    const cellRef = useRef<HTMLDivElement>(null);

    const outputStale = outputIsStale(
      {
        status,
        output,
        interrupted,
        runStartTimestamp,
        staleInputs,
      },
      false,
    );
    const loading = outputIsLoading(status);

    // Kiosk and not presenting
    const kioskFull = kiosk && mode !== "present";

    const isPureMarkdown = new MarkdownLanguageAdapter().isSupported(code);
    const published = !showCode && !kioskFull;
    const className = cn(
      "sp-cell",
      "hover-actions-parent empty:invisible",
      {
        published: published,
        "has-error": errored,
        stopped: stopped,
        borderless: isPureMarkdown && !published,
      },
    );

    // Read mode and show code
    if ((mode === "read" && showCode) || kioskFull) {
      const outputArea = (
        <OutputArea
          allowExpand={true}
          output={output}
          className={CSSClasses.outputArea}
          cellId={cellId}
          stale={outputStale}
          loading={loading}
        />
      );

      // Hide the code if it's pure markdown and there's an output, or if the
      // code is empty. Cells explicitly marked hide_code render no code tray
      // at all in the read view (scaffold/plumbing cells — e.g. the chat
      // analysis notebook's seeded setup cells); kiosk viewers still get the
      // collapsed-but-expandable tray for ordinary cells below.
      const hideCode = shouldHideCode(code, output) || config.hide_code === true;

      return (
        <div
          tabIndex={-1}
          ref={cellRef}
          className={className}
          {...cellDomProps(cellId, name)}
        >
          {cellOutputArea === "above" && outputArea}
          {!hideCode && (
            <div className="tray">
              <ReadonlyCode
                initiallyHideCode={config.hide_code || kiosk}
                code={code}
              />
            </div>
          )}
          {cellOutputArea === "below" && outputArea}
          <ConsoleOutput
            consoleOutputs={consoleOutputs}
            stale={outputStale}
            cellName={name}
            onSubmitDebugger={() => null}
            cellId={cellId}
            debuggerActive={false}
          />
        </div>
      );
    }

    const outputIsError = isErrorMime(output?.mimetype);
    // When show_tracebacks is enabled, show error outputs inline
    // instead of hiding them
    const hasTraceback =
      showErrorTracebacks &&
      outputIsError &&
      Array.isArray(output?.data) &&
      output.data.some(
        (e: SpError) =>
          e.type === "exception" && "traceback" in e && e.traceback,
      );
    const hidden =
      (errored || interrupted || stopped || outputIsError) && !hasTraceback;
    if (hidden) {
      return null;
    }

    return (
      <div
        tabIndex={-1}
        ref={cellRef}
        className={className}
        {...cellDomProps(cellId, name)}
      >
        <OutputArea
          allowExpand={mode === "edit"}
          output={output}
          className={CSSClasses.outputArea}
          cellId={cellId}
          stale={outputStale}
          loading={loading}
        />
      </div>
    );
  },
);
VerticalCell.displayName = "VerticalCell";

export const VerticalLayoutPlugin: ICellRendererPlugin<
  VerticalLayout,
  VerticalLayout
> = {
  type: "vertical",
  name: "Vertical",
  validator: z.any(),
  Component: VerticalLayoutRenderer,
  deserializeLayout: (serialized) => serialized,
  serializeLayout: (layout) => layout,
  getInitialLayout: () => null,
};

export function groupCellsByColumn(
  cells: (CellRuntimeState & CellData)[],
): [number, (CellRuntimeState & CellData)[]][] {
  // Group cells by column
  const cellsByColumn = new Map<number, (CellRuntimeState & CellData)[]>();
  let lastSeenColumn = 0;
  cells.forEach((cell) => {
    const column = cell.config.column ?? lastSeenColumn;
    lastSeenColumn = column;
    if (!cellsByColumn.has(column)) {
      cellsByColumn.set(column, []);
    }
    cellsByColumn.get(column)?.push(cell);
  });

  // Sort columns by index
  return [...cellsByColumn.entries()].toSorted(([a], [b]) => a - b);
}

/**
 * Determine if the code should be hidden.
 *
 * This is used to hide the code if it's pure markdown and there's an output,
 * or if the code is empty.
 */
export function shouldHideCode(code: string, output: OutputMessage | null) {
  const isPureMarkdown = new MarkdownLanguageAdapter().isSupported(code);
  const hasOutput = output !== null && !isOutputEmpty(output);
  return (isPureMarkdown && hasOutput) || code.trim() === "";
}
