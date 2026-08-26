import { useAtomValue } from "jotai";
import { memo } from "react";
import useEvent from "react-use-event-hook";
import { connectionAtom } from "@/core/network/connection";
import type { CellId } from "@/core/cells/ids";
import { cn } from "@/utils/cn";
import { renderShortcut } from "@/components/shortcuts/renderShortcut";
import { CreateCellButton } from "./CreateCellButton";
import type { CellComponentActions } from "./cell-types";

export const CellLeftSideActions = memo(
  (props: {
    className?: string;
    cellId: CellId;
    actions: CellComponentActions;
  }) => {
    const connection = useAtomValue(connectionAtom);
    const { className, actions, cellId } = props;

    const createBelow = useEvent(
      (opts: { code?: string; hideCode?: boolean } = {}) =>
        actions.createNewCell({ cellId, before: false, ...opts }),
    );
    const createAbove = useEvent(
      (opts: { code?: string; hideCode?: boolean } = {}) =>
        actions.createNewCell({ cellId, before: true, ...opts }),
    );

    const oneClickShortcut = "mod";

    return (
      <div
        className={cn(
          "absolute flex flex-col justify-center h-full left-[-26px] z-20 border-b-0!",
          className,
        )}
      >
        <div className="-mt-1 min-h-7">
          <CreateCellButton
            tooltipContent={renderShortcut("cell.createAbove")}
            connectionState={connection.state}
            onClick={createAbove}
            oneClickShortcut={oneClickShortcut}
          />
        </div>
        <div className="flex-1 pointer-events-none w-3" />
        {/* <div className="flex-1 pointer-events-none bg-border w-px mx-auto hover-action opacity-70" /> */}
        <div className="-mb-2 min-h-7">
          <CreateCellButton
            tooltipContent={renderShortcut("cell.createBelow")}
            connectionState={connection.state}
            onClick={createBelow}
            oneClickShortcut={oneClickShortcut}
          />
        </div>
      </div>
    );
  },
);

CellLeftSideActions.displayName = "CellLeftSideActions";
