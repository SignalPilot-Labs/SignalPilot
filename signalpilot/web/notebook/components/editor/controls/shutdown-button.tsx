import { ArrowLeftIcon } from "lucide-react";

import { Tooltip } from "../../ui/tooltip";
import { Button } from "../inputs/Inputs";

interface Props {
  description?: string;
  tooltip?: string;
}

export const ShutdownButton: React.FC<Props> = ({
  tooltip = "Back to home",
}) => {
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
          window.location.href = "/projects";
        }}
      >
        <ArrowLeftIcon strokeWidth={1.5} />
      </Button>
    </Tooltip>
  );
};
