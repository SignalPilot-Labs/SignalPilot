import { useAtomValue } from "jotai";
import {
  EditIcon,
  LayoutTemplateIcon,
  PlayIcon,
  RefreshCwIcon,
  SaveIcon,
  SquareIcon,
  Undo2Icon,
} from "lucide-react";
import type { JSX } from "react";
import { NotebookMenuDropdown } from "@/components/editor/controls/notebook-menu-dropdown";
import { ShutdownButton } from "@/components/editor/controls/shutdown-button";
import { Button } from "@/components/editor/inputs/Inputs";
import { FindReplace } from "@/components/find-replace/find-replace";
import type { AppConfig } from "@/core/config/config-schema";
import { useActiveTab } from "@/core/file-tabs";
import { canInteractWithAppAtom } from "@/core/network/connection";
import { SaveComponent } from "@/core/saving/save-component";
import {
  getConnectionTooltip,
  isAppInteractionDisabled,
} from "@/core/websocket/connection-utils";
import { WebSocketState } from "@/core/websocket/types";
import { cn } from "@/utils/cn";
import { Functions } from "@/utils/functions";
import {
  canUndoDeletesAtom,
  needsRunAtom,
  undoLabelAtom,
  useCellActions,
} from "../../../core/cells/cells";
import { ConfigButton } from "../../app-config/app-config-button";
import { renderShortcut } from "../../shortcuts/renderShortcut";
import { Tooltip } from "../../ui/tooltip";
import { useShouldShowInterrupt } from "../cell/useShouldShowInterrupt";
import { HideInKioskMode } from "../kiosk-mode";
import { LayoutSelect } from "../renderers/layout-select";
import { DbtToolbar } from "../dbt/dbt-toolbar";
import { rawFileNeedsSaveAtom, rawFileSaveFnAtom } from "../raw-file-editor";
import { CommandPaletteButton } from "./command-palette-button";

interface ControlsProps {
  presenting: boolean;
  onTogglePresenting: () => void;
  onInterrupt: () => void;
  onRun: () => void;
  onRunAll: () => void;
  connectionState: WebSocketState;
  running: boolean;
  appConfig: AppConfig;
}

export const Controls = ({
  presenting,
  onTogglePresenting,
  onInterrupt,
  onRun,
  onRunAll,
  connectionState,
  running,
}: ControlsProps): JSX.Element => {
  const undoAvailable = useAtomValue(canUndoDeletesAtom);
  const undoLabel = useAtomValue(undoLabelAtom);
  const needsRun = useAtomValue(needsRunAtom);
  const { undoDeleteCell } = useCellActions();
  const closed = connectionState === WebSocketState.CLOSED;
  const activeTab = useActiveTab();
  const isRawFileView = activeTab?.type === "raw";

  const disabled = isAppInteractionDisabled(connectionState);
  const connectionTooltip = disabled
    ? getConnectionTooltip(connectionState)
    : undefined;

  if (isRawFileView) {
    return <RawFileControls disabled={disabled} connectionTooltip={connectionTooltip} closed={closed} />;
  }

  let undoControl: JSX.Element | null = null;
  if (!closed && undoAvailable) {
    undoControl = (
      <Tooltip content={undoLabel}>
        <Button
          data-testid="undo-delete-cell"
          size="medium"
          color="hint-green"
          shape="circle"
          onClick={undoDeleteCell}
        >
          <Undo2Icon size={16} strokeWidth={1.5} />
        </Button>
      </Tooltip>
    );
  }

  return (
    <>
      {!presenting && <FindReplace />}

      <div className={topRightControls}>
        {!closed && (
          <>
            {!presenting && <DbtToolbar />}
            {presenting && <LayoutSelect />}
            <NotebookMenuDropdown
              disabled={disabled}
              tooltip={connectionTooltip}
            />
            <ConfigButton disabled={disabled} tooltip={connectionTooltip} />
          </>
        )}
        <ShutdownButton
          description="This will terminate the Python kernel. You'll lose all data that's in memory."
        />
      </div>

      <div className={cn(bottomRightControls)}>
        <HideInKioskMode>
          <SaveComponent kioskMode={false} />
        </HideInKioskMode>

        <Tooltip content={renderShortcut("global.hideCode")}>
          <Button
            data-testid="hide-code-button"
            id="preview-button"
            shape="rectangle"
            color="hint-green"
            onClick={onTogglePresenting}
          >
            {presenting ? (
              <EditIcon strokeWidth={1.5} size={18} />
            ) : (
              <LayoutTemplateIcon strokeWidth={1.5} size={18} />
            )}
          </Button>
        </Tooltip>

        <CommandPaletteButton />

        <div />

        <HideInKioskMode>
          <div className="flex flex-col gap-2 items-center">
            {undoControl}
            {!closed && (
              <StopControlButton running={running} onInterrupt={onInterrupt} />
            )}
            {!closed && <RunControlButton needsRun={needsRun} onRun={onRun} onRunAll={onRunAll} />}
          </div>
        </HideInKioskMode>
      </div>
    </>
  );
};

// ── Raw file controls (no run/stop/undo/layout) ─────────────────

const RawFileControls: React.FC<{
  disabled: boolean;
  connectionTooltip: string | undefined;
  closed: boolean;
}> = ({ disabled, connectionTooltip, closed }) => {
  const rawNeedsSave = useAtomValue(rawFileNeedsSaveAtom);
  const rawSaveFn = useAtomValue(rawFileSaveFnAtom);

  return (
    <>
      <FindReplace />

      <div className={topRightControls}>
        {!closed && (
          <>
            <DbtToolbar />
            <NotebookMenuDropdown
              disabled={disabled}
              tooltip={connectionTooltip}
            />
            <ConfigButton disabled={disabled} tooltip={connectionTooltip} />
          </>
        )}
        <ShutdownButton
          description="This will terminate the Python kernel. You'll lose all data that's in memory."
        />
      </div>

      <div className={cn(bottomRightControls)}>
        <Tooltip content={renderShortcut("global.save")}>
          <Button
            data-testid="save-button"
            shape="rectangle"
            color={rawNeedsSave ? "yellow" : "hint-green"}
            onClick={() => rawSaveFn?.()}
          >
            <SaveIcon strokeWidth={1.5} size={18} />
          </Button>
        </Tooltip>
        <CommandPaletteButton />
      </div>
    </>
  );
};

// ── Notebook-only buttons ────────────────────────────────────────

const RunControlButton = ({
  needsRun,
  onRun,
  onRunAll,
}: {
  needsRun: boolean;
  onRun: () => void;
  onRunAll: () => void;
}) => {
  const canInteractWithApp = useAtomValue(canInteractWithAppAtom);

  if (needsRun) {
    return (
      <Tooltip content={renderShortcut("global.runStale")}>
        <Button
          data-testid="run-button"
          size="medium"
          color="yellow"
          shape="circle"
          onClick={onRun}
          disabled={!canInteractWithApp}
        >
          <PlayIcon strokeWidth={1.5} size={16} />
        </Button>
      </Tooltip>
    );
  }

  return (
    <Tooltip content="Re-run all cells">
      <Button
        data-testid="run-button"
        size="medium"
        color="hint-green"
        shape="circle"
        onClick={onRunAll}
        disabled={!canInteractWithApp}
      >
        <RefreshCwIcon strokeWidth={1.5} size={16} />
      </Button>
    </Tooltip>
  );
};

const StopControlButton = ({
  running,
  onInterrupt,
}: {
  running: boolean;
  onInterrupt: () => void;
}) => {
  const showInterrupt = useShouldShowInterrupt(running);

  return (
    <Tooltip content={renderShortcut("global.interrupt")}>
      <Button
        className={cn(
          !showInterrupt && "inactive-button active:shadow-xs-solid",
        )}
        data-testid="interrupt-button"
        size="medium"
        color={showInterrupt ? "yellow" : "disabled"}
        shape="circle"
        onClick={showInterrupt ? onInterrupt : Functions.NOOP}
      >
        <SquareIcon strokeWidth={1.5} size={16} />
      </Button>
    </Tooltip>
  );
};

const topRightControls =
  "absolute top-3 right-5 m-0 flex items-center gap-2 min-h-[28px] print:hidden pointer-events-auto z-30";

const bottomRightControls =
  "absolute bottom-5 right-5 flex flex-col gap-2 items-center print:hidden pointer-events-auto z-30";
