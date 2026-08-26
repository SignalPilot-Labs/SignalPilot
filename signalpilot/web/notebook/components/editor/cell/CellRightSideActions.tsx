import { memo } from "react";
import type { RuntimeState } from "@/core/network/types";
import { cn } from "@/utils/cn";
import type { Milliseconds, Seconds } from "@/utils/time";
import { CellDragHandle } from "../SortableCell";
import { CellStatusComponent } from "./CellStatus";

export const CellRightSideActions = memo(
  (props: {
    className?: string;
    disabled: boolean | undefined;
    edited: boolean;
    interrupted: boolean;
    isCellStatusInline: boolean;
    lastRunStartTimestamp: Seconds | null;
    runElapsedTimeMs: Milliseconds | null;
    runStartTimestamp: Seconds | null;
    staleInputs: boolean;
    status: RuntimeState;
    uninstantiated: boolean;
  }) => {
    const {
      className,
      disabled = false,
      edited,
      interrupted,
      isCellStatusInline,
      lastRunStartTimestamp,
      runElapsedTimeMs,
      runStartTimestamp,
      staleInputs,
      status,
      uninstantiated,
    } = props;

    const cellStatusComponent = (
      <CellStatusComponent
        status={status}
        staleInputs={staleInputs}
        interrupted={interrupted}
        editing={true}
        edited={edited}
        disabled={disabled}
        elapsedTime={runElapsedTimeMs}
        runStartTimestamp={runStartTimestamp}
        uninstantiated={uninstantiated}
        lastRunStartTimestamp={lastRunStartTimestamp}
      />
    );

    return (
      <div className={cn("shoulder-right z-20", className)}>
        {!isCellStatusInline && cellStatusComponent}
        <div className="flex gap-2 items-end">
          <CellDragHandle />
          {isCellStatusInline && cellStatusComponent}
        </div>
      </div>
    );
  },
);

CellRightSideActions.displayName = "CellRightSideActions";
