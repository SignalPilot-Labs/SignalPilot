import {
  DatabaseIcon,
  HammerIcon,
  Loader2Icon,
  PlayIcon,
  TestTubeIcon,
  WrenchIcon,
} from "lucide-react";
import React from "react";
import { Button } from "@/components/ui/button";
import { Tooltip } from "@/components/ui/tooltip";
import { cn } from "@/utils/cn";
import { useChromeActions } from "../chrome/state";
import { useDbtActions, useDbtStatus } from "./use-dbt";

export const DbtToolbar: React.FC = () => {
  const status = useDbtStatus();
  const { runCommand } = useDbtActions();
  const { toggleApplication } = useChromeActions();
  const isRunning = status === "running";

  return (
    <div className="flex items-center gap-1 border border-border rounded-md px-1 py-0.5 bg-background/80 backdrop-blur-sm">
      <Tooltip content="dbt output panel">
        <Button
          variant="text"
          size="xs"
          className={cn(
            "h-6 w-6 p-0",
            status === "error" && "text-red-500",
            status === "success" && "text-green-500",
          )}
          onClick={() => toggleApplication("dbt")}
        >
          <DatabaseIcon size={14} />
        </Button>
      </Tooltip>

      <div className="w-px h-4 bg-border" />

      <Tooltip content="dbt run">
        <Button
          variant="text"
          size="xs"
          className="h-6 px-1.5 text-xs font-mono gap-1"
          disabled={isRunning}
          onClick={() => runCommand("run")}
        >
          {isRunning ? (
            <Loader2Icon size={12} className="animate-spin" />
          ) : (
            <PlayIcon size={12} />
          )}
          run
        </Button>
      </Tooltip>

      <Tooltip content="dbt build (run + test + seed + snapshot)">
        <Button
          variant="text"
          size="xs"
          className="h-6 px-1.5 text-xs font-mono gap-1"
          disabled={isRunning}
          onClick={() => runCommand("build")}
        >
          <HammerIcon size={12} />
          build
        </Button>
      </Tooltip>

      <Tooltip content="dbt test">
        <Button
          variant="text"
          size="xs"
          className="h-6 px-1.5 text-xs font-mono gap-1"
          disabled={isRunning}
          onClick={() => runCommand("test")}
        >
          <TestTubeIcon size={12} />
          test
        </Button>
      </Tooltip>

      <Tooltip content="dbt compile">
        <Button
          variant="text"
          size="xs"
          className="h-6 px-1.5 text-xs font-mono gap-1"
          disabled={isRunning}
          onClick={() => runCommand("compile")}
        >
          <WrenchIcon size={12} />
          compile
        </Button>
      </Tooltip>
    </div>
  );
};
