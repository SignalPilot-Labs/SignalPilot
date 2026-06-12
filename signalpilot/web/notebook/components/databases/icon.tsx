import { DatabaseIcon } from "lucide-react";
import type { FC } from "react";
import { cn } from "@/utils/cn";

interface DatabaseLogoProps {
  name: string;
  className?: string;
}

export const DatabaseLogo: FC<DatabaseLogoProps> = ({ name, className }) => {
  return <DatabaseIcon className={cn("mt-0.5", className)} />;
};
