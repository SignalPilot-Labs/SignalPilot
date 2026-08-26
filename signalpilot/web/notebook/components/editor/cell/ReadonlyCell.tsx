import clsx from "clsx";
import { forwardRef } from "react";
import { outputIsLoading, outputIsStale } from "@/core/cells/cell";
import { isErrorMime } from "@/core/mime";
import { CSSClasses } from "@/core/constants";
import { useCellData, useCellRuntime } from "@/core/cells/cells";
import type { CellId } from "@/core/cells/ids";
import { cellDomProps } from "../common";
import { OutputArea } from "../Output";

export const ReadonlyCellComponent = forwardRef(
  (props: { cellId: CellId }, ref: React.ForwardedRef<HTMLDivElement>) => {
    const { cellId } = props;
    const cellData = useCellData(cellId);
    const cellRuntime = useCellRuntime(cellId);

    const className = clsx("sp-cell", "hover-actions-parent z-10", {
      published: true,
    });

    const outputIsError = isErrorMime(cellRuntime.output?.mimetype);

    // Hide the output if it's an error or stopped.
    const hidden =
      cellRuntime.errored ||
      cellRuntime.interrupted ||
      cellRuntime.stopped ||
      outputIsError;

    if (hidden) {
      return null;
    }

    return (
      <div
        tabIndex={-1}
        ref={ref}
        className={className}
        {...cellDomProps(cellId, cellData.name)}
      >
        <OutputArea
          allowExpand={false}
          forceExpand={true}
          className={CSSClasses.outputArea}
          cellId={cellId}
          output={cellRuntime.output}
          stale={outputIsStale(cellRuntime, cellData.edited)}
          loading={outputIsLoading(cellRuntime.status)}
        />
      </div>
    );
  },
);
ReadonlyCellComponent.displayName = "ReadonlyCellComponent";
