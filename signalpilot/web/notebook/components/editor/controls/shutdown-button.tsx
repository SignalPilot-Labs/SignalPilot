import { ArrowLeftIcon } from "lucide-react";
import { navigate } from "@/embed/host-navigate";

import { Tooltip } from "../../ui/tooltip";
import { Button } from "../inputs/Inputs";

interface Props {
  description?: string;
  disabled?: boolean;
  tooltip?: string;
}

export const ShutdownButton: React.FC<Props> = ({
  disabled = false,
  tooltip = "Back to home",
}) => {
  return (
    <Tooltip content={tooltip}>
      <Button
        aria-label="Back to home"
        data-testid="back-button"
        shape="circle"
        size="small"
        color={disabled ? "disabled" : "hint-green"}
        className="h-[27px] w-[27px]"
        disabled={disabled}
        onClick={(e) => {
          e.stopPropagation();
          const withoutSearch = document.baseURI.split("?")[0];
          navigate(withoutSearch);
        }}
      >
        <ArrowLeftIcon strokeWidth={1.5} />
      </Button>
    </Tooltip>
  );
};
