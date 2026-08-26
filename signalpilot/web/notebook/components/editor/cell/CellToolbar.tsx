import type { EditorView } from "@codemirror/view";
import { useAtomValue } from "jotai";
import { MoreHorizontalIcon } from "lucide-react";
import { memo } from "react";
import { connectionAtom } from "@/core/network/connection";
import type { CellConfig, RuntimeState } from "@/core/network/types";
import type { CellId } from "@/core/cells/ids";
import { cn } from "@/utils/cn";
import {
  CellActionsDropdown,
  type CellActionsDropdownHandle,
} from "./cell-actions";
import { RunButton } from "./RunButton";
import { StopButton } from "./StopButton";
import { Toolbar, ToolbarItem } from "./toolbar";

interface CellToolbarProps {
  edited: boolean;
  status: RuntimeState;
  cellConfig: CellConfig;
  needsRun: boolean;
  hasOutput: boolean;
  hasConsoleOutput: boolean;
  cellActionDropdownRef: React.RefObject<CellActionsDropdownHandle | null>;
  cellId: CellId;
  name: string;
  includeCellActions?: boolean;
  getEditorView: () => EditorView | null;
  onRun: () => void;
}

export const CellToolbar = memo(
  ({
    edited,
    status,
    cellConfig,
    needsRun,
    hasOutput,
    hasConsoleOutput,
    onRun,
    cellActionDropdownRef,
    cellId,
    getEditorView,
    name,
    includeCellActions = true,
  }: CellToolbarProps) => {
    const connection = useAtomValue(connectionAtom);

    return (
      <Toolbar
        className={cn(
          // Show the toolbar on hover, or when the cell needs to be run
          !needsRun && "hover-action",
        )}
      >
        <RunButton
          edited={edited}
          onClick={onRun}
          connectionState={connection.state}
          status={status}
          config={cellConfig}
          needsRun={needsRun}
        />
        <StopButton status={status} connectionState={connection.state} />
        {includeCellActions && (
          <CellActionsDropdown
            ref={cellActionDropdownRef}
            cellId={cellId}
            status={status}
            getEditorView={getEditorView}
            name={name}
            config={cellConfig}
            hasOutput={hasOutput}
            hasConsoleOutput={hasConsoleOutput}
          >
            <ToolbarItem
              variant={"green"}
              tooltip={null}
              data-testid="cell-actions-button"
            >
              <MoreHorizontalIcon strokeWidth={1.5} />
            </ToolbarItem>
          </CellActionsDropdown>
        )}
      </Toolbar>
    );
  },
);

CellToolbar.displayName = "CellToolbar";
