import { PartyPopperIcon } from "lucide-react";
import React from "react";
import { CellLinkError } from "@/components/editor/links/cell-link";
import { useCellErrors } from "../../../../core/cells/cells";
import { SpErrorOutput } from "../../output/SpErrorOutput";
import { PanelEmptyState } from "./empty-state";

const ErrorsPanel: React.FC = () => {
  const errors = useCellErrors();

  if (errors.length === 0) {
    return <PanelEmptyState title="No errors!" icon={<PartyPopperIcon />} />;
  }

  return (
    <div className="flex flex-col h-full overflow-auto">
      {errors.map((error) => (
        <div key={error.cellId}>
          <div className="text-xs font-mono font-semibold bg-muted border-y px-2 py-1">
            <CellLinkError cellId={error.cellId} />
          </div>
          <div key={error.cellId} className="px-2">
            <SpErrorOutput
              key={error.cellId}
              errors={error.output.data}
              cellId={error.cellId}
            />
          </div>
        </div>
      ))}
    </div>
  );
};

export default ErrorsPanel;
