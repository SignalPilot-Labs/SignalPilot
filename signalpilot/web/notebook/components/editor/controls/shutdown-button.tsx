import { ArrowLeftIcon } from "lucide-react";

import { Tooltip } from "../../ui/tooltip";
import { Button } from "../inputs/Inputs";
import { tryGetNotebookConfig } from "~/components/notebook/notebook-context";

interface Props {
  description?: string;
  tooltip?: string;
}

export const ShutdownButton: React.FC<Props> = ({
  tooltip = "Back to home",
}) => {
  const config = tryGetNotebookConfig();
  const queryHasProject =
    typeof window !== "undefined" &&
    new URLSearchParams(window.location.search).has("project");
  const homePath =
    config?.product === "notebooks"
      ? "/projects"
      : config?.product === "projects" || config?.project || queryHasProject
        ? "/projects"
        : "/projects";

  return (
    <Tooltip content={tooltip}>
      <Button
        aria-label="Back to home"
        data-testid="back-button"
        shape="circle"
        size="small"
        color="hint-green"
        className="h-[27px] w-[27px]"
        onClick={(e) => {
          e.stopPropagation();
          window.location.href = homePath;
        }}
      >
        <ArrowLeftIcon strokeWidth={1.5} />
      </Button>
    </Tooltip>
  );
};
