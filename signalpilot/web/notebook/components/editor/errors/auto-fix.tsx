import { useAtomValue, useStore } from "jotai";
import { WrenchIcon } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Tooltip } from "@/components/ui/tooltip";
import { notebookAtom, useCellActions } from "@/core/cells/cells";
import type { CellId } from "@/core/cells/ids";
import { aiEnabledAtom } from "@/core/config/config";
import { getAutoFixes } from "@/core/errors/errors";
import type { SpError } from "@/core/kernel/messages";
import { cn } from "@/utils/cn";

export const AutoFixButton = ({
  errors,
  cellId,
  className,
}: {
  errors: SpError[];
  cellId: CellId;
  className?: string;
}) => {
  const store = useStore();
  const { createNewCell } = useCellActions();
  const aiEnabled = useAtomValue(aiEnabledAtom);
  const autoFixes = errors.flatMap((error) =>
    getAutoFixes(error, { aiEnabled }),
  );

  if (autoFixes.length === 0) {
    return null;
  }

  const firstFix = autoFixes[0];

  const handleFix = () => {
    const editorView =
      store.get(notebookAtom).cellHandles[cellId].current?.editorView;
    firstFix.onFix({
      addCodeBelow: (code: string) => {
        createNewCell({
          cellId: cellId,
          autoFocus: false,
          before: false,
          code: code,
        });
      },
      editor: editorView,
      cellId: cellId,
    });
    // Focus the editor
    editorView?.focus();
  };

  return (
    <div className={cn("my-2", className)}>
      <Tooltip content={firstFix.description} align="start">
        <Button
          size="xs"
          variant="outline"
          className="font-normal"
          onClick={handleFix}
        >
          <WrenchIcon className="h-3 w-3 mr-2" />
          {firstFix.title}
        </Button>
      </Tooltip>
    </div>
  );
};
