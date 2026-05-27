import { useAtom } from "jotai";
import {
  BotIcon,
  CheckIcon,
  GitBranchIcon,
  Loader2Icon,
  RefreshCwIcon,
} from "lucide-react";
import React, { useCallback, useEffect, useMemo, useState } from "react";
import { Button } from "@/components/ui/button";
import { useConfirmDialog } from "@/components/ui/confirm-dialog";
import { Tooltip } from "@/components/ui/tooltip";
import {
  branchListAtom,
  fetchBranches,
  gatewayBranchIdAtom,
  hasUncommittedChanges,
  switchBranch,
} from "@/core/branch/branch-state";
import { cn } from "@/utils/cn";

const AGENT_PREFIX = "signalpilot-agent/";

function parseAgentBranchName(name: string): {
  task: string;
  timestamp: string;
} {
  const suffix = name.slice(AGENT_PREFIX.length);
  const lastSlash = suffix.lastIndexOf("/");
  if (lastSlash > 0) {
    return {
      task: suffix.slice(0, lastSlash),
      timestamp: suffix.slice(lastSlash + 1),
    };
  }
  return { task: suffix, timestamp: "" };
}

const AgentBranchesPanel: React.FC = () => {
  const [branchId, setBranchId] = useAtom(gatewayBranchIdAtom);
  const [branches, setBranches] = useAtom(branchListAtom);
  const [loading, setLoading] = useState(false);
  const { confirm, dialog: confirmDialog } = useConfirmDialog();

  const currentBranch = branchId || "main";

  const loadBranches = useCallback(async () => {
    setLoading(true);
    const list = await fetchBranches();
    setBranches(list);
    setLoading(false);
  }, [setBranches]);

  useEffect(() => {
    loadBranches();
  }, [loadBranches]);

  const agentBranches = useMemo(
    () =>
      branches
        .filter((b) => b.name.startsWith(AGENT_PREFIX))
        .sort((a, b) => (b.timestamp || 0) - (a.timestamp || 0)),
    [branches],
  );

  const handleSwitch = async (name: string) => {
    if (name === currentBranch) {return;}
    const dirty = await hasUncommittedChanges();
    if (dirty && dirty.length > 0) {
      const ok = await confirm({
        title: "Switch Branch",
        description: `Switch to "${name}"? You have ${dirty.length} uncommitted file(s) that will be lost.`,
        confirmLabel: "Discard & switch",
        variant: "destructive",
      });
      if (!ok) {return;}
    }
    await switchBranch(name);
    setBranchId(name);
    const url = new URL(window.location.href);
    url.searchParams.set("branch", name);
    window.location.href = url.toString();
  };

  return (
    <>
    {confirmDialog}
    <div className="flex flex-col h-full overflow-hidden">
      <div className="flex items-center justify-between px-3 py-2 border-b border-border">
        <span className="text-[10px] uppercase tracking-wider font-semibold text-muted-foreground">
          Agent Branches
        </span>
        <Tooltip content="Refresh" side="left">
          <Button
            variant="text"
            size="xs"
            onClick={loadBranches}
            disabled={loading}
          >
            <RefreshCwIcon
              size={12}
              className={loading ? "animate-spin" : ""}
            />
          </Button>
        </Tooltip>
      </div>

      <div className="flex-1 overflow-y-auto">
        {loading && agentBranches.length === 0 ? (
          <div className="flex items-center justify-center py-8 text-muted-foreground text-xs">
            <Loader2Icon size={14} className="animate-spin mr-2" />
            Loading...
          </div>
        ) : agentBranches.length === 0 ? (
          <div className="flex flex-col items-center justify-center py-8 px-4 text-center gap-2">
            <BotIcon size={24} className="text-muted-foreground/50" />
            <span className="text-xs text-muted-foreground">
              No agent branches found
            </span>
            <span className="text-[10px] text-muted-foreground/70">
              Branches prefixed with{" "}
              <code className="px-1 py-0.5 rounded bg-muted font-mono">
                signalpilot-agent/
              </code>{" "}
              will appear here.
            </span>
          </div>
        ) : (
          <div className="py-1">
            {agentBranches.map((b) => {
              const { task, timestamp: _timestamp } = parseAgentBranchName(b.name);
              const isCurrent = b.name === currentBranch;
              return (
                <button
                  key={b.name}
                  type="button"
                  className={cn(
                    "w-full flex items-start gap-2.5 px-3 py-2 text-left",
                    "hover:bg-muted/50 cursor-pointer",
                    "border-b border-border/50 last:border-b-0",
                    isCurrent && "bg-primary/5",
                  )}
                  onClick={() => handleSwitch(b.name)}
                >
                  <GitBranchIcon
                    size={13}
                    className={cn(
                      "shrink-0 mt-0.5",
                      isCurrent ? "text-purple-400" : "text-muted-foreground",
                    )}
                  />
                  <div className="flex-1 min-w-0">
                    <div className="flex items-center gap-1.5">
                      <span
                        className={cn(
                          "text-xs font-medium truncate",
                          isCurrent && "text-purple-400",
                        )}
                      >
                        {task}
                      </span>
                      {isCurrent && (
                        <CheckIcon size={11} className="shrink-0 text-purple-400" />
                      )}
                    </div>
                    <div className="flex items-center gap-2 mt-0.5">
                      <span className="text-[10px] text-muted-foreground/70">
                        Last updated: {b.date || "unknown"}
                      </span>
                    </div>
                    <div className="flex items-center gap-2 mt-0.5">
                      {b.sha && (
                        <span className="text-[9px] font-mono text-muted-foreground/50">
                          {b.sha}
                        </span>
                      )}
                      {b.is_remote && !b.is_local && (
                        <span className="text-[9px] px-1 rounded bg-blue-500/10 text-blue-500">
                          remote
                        </span>
                      )}
                    </div>
                  </div>
                </button>
              );
            })}
          </div>
        )}
      </div>
    </div>
    </>
  );
};

export default AgentBranchesPanel;
