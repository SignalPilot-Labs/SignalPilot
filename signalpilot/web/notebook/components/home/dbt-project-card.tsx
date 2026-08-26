import {
  DatabaseIcon,
  FolderOpenIcon,
} from "lucide-react";
import type React from "react";
import { cn } from "@/utils/cn";
import { timeAgo } from "@/utils/dates";
import type { DbtProjectSummary } from "../editor/dbt/types";

interface Props {
  project: DbtProjectSummary;
  onClick: (project: DbtProjectSummary) => void;
}

export const DbtProjectCard: React.FC<Props> = ({ project, onClick }) => {
  const name = project.projectName || project.projectDir.split(/[/\\]/).pop() || "Unknown";
  const relativePath = project.projectDir;

  return (
    <button
      type="button"
      className={cn(
        "w-full text-left p-4 rounded-lg border border-border",
        "hover:border-primary/40 hover:bg-muted/50 transition-all duration-150",
        "cursor-pointer group",
      )}
      onClick={() => onClick(project)}
    >
      <div className="flex items-start gap-3">
        <div className="mt-0.5 p-2 rounded-md bg-primary/10 text-primary">
          <DatabaseIcon size={18} />
        </div>
        <div className="flex-1 min-w-0">
          <div className="font-semibold text-sm truncate">{name}</div>
          {project.profile && (
            <div className="text-xs text-muted-foreground mt-0.5">
              profile: {project.profile}
            </div>
          )}
          <div className="flex items-center gap-1 text-xs text-muted-foreground mt-1">
            <FolderOpenIcon size={10} />
            <span className="truncate">{relativePath}</span>
          </div>
          {project.lastModified && (
            <div className="text-[10px] text-muted-foreground mt-1">
              {timeAgo(project.lastModified * 1000, navigator.language)}
            </div>
          )}
        </div>
      </div>
    </button>
  );
};
