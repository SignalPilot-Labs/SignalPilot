import { CloudIcon, CloudOffIcon, Loader2Icon, RefreshCwIcon } from "lucide-react";
import React from "react";
import { type FetchStatus, gitFetch, gitPull } from "@/core/branch/branch-state";
import { spApiUrl } from "@/core/network/api";
import { getApiHeaders } from "@/core/network/api-headers";
import { BranchStatus } from "@/components/editor/chrome/wrapper/footer-items/branch-status";
import { Button } from "@/components/ui/button";
import { Tooltip } from "@/components/ui/tooltip";
import { cn } from "@/utils/cn";

export type SyncState = "checking" | "synced" | "behind" | "ahead" | "diverged" | "pulling" | "error" | "no-remote";

export const CloudSyncBar: React.FC<{ onSynced: () => void }> = ({ onSynced }) => {
  const [state, setState] = React.useState<SyncState>("checking");
  const [fetchInfo, setFetchInfo] = React.useState<FetchStatus | null>(null);
  const [detail, setDetail] = React.useState("");
  const [pulling, setPulling] = React.useState(false);
  const [confirmingReset, setConfirmingReset] = React.useState(false);
  const [resetting, setResetting] = React.useState(false);

  const checkStatus = React.useCallback(async () => {
    setState("checking");
    const result = await gitFetch();
    if (!result) {
      setState("error");
      setDetail("Could not fetch");
      return;
    }
    setFetchInfo(result);
    if (!result.has_remote) {
      setState("no-remote");
      setDetail("Local only (no remote)");
    } else if (result.ahead === 0 && result.behind === 0) {
      setState("synced");
      setDetail("Up to date");
    } else if (result.behind > 0 && result.ahead === 0) {
      setState("behind");
      setDetail(`${result.behind} commit${result.behind > 1 ? "s" : ""} behind`);
    } else if (result.ahead > 0 && result.behind === 0) {
      setState("ahead");
      setDetail(`${result.ahead} unpushed commit${result.ahead > 1 ? "s" : ""}`);
    } else {
      setState("diverged");
      setDetail(`${result.ahead} ahead, ${result.behind} behind`);
    }
  }, []);

  React.useEffect(() => {
    checkStatus();
    const interval = setInterval(checkStatus, 5 * 60 * 1000);
    return () => clearInterval(interval);
  }, [checkStatus]);

  const handlePull = React.useCallback(async () => {
    setPulling(true);
    const result = await gitPull();
    setPulling(false);
    if (result.success) {
      setState("synced");
      setDetail("Pulled successfully");
      onSynced();
    } else if (result.conflict) {
      setState("error");
      setDetail(`Merge conflict in ${result.files?.length || 0} file(s)`);
    } else {
      setState("error");
      setDetail(result.error || "Pull failed");
    }
  }, [onSynced]);

  const handleForceReset = React.useCallback(async () => {
    setResetting(true);
    setConfirmingReset(false);
    setState("checking");
    setDetail("Resetting...");
    try {
      const resp = await fetch(spApiUrl("/git/force-reset"), { method: "POST", headers: await getApiHeaders() });
      const data = await resp.json() as { success?: boolean; file_count?: number; error?: string };
      if (data.success) {
        setState("synced");
        setDetail(`Reset complete: ${data.file_count} files`);
        onSynced();
      } else {
        setState("error");
        setDetail(data.error || "Reset failed");
      }
    } catch (e) {
      setState("error");
      setDetail(String(e));
    }
    setResetting(false);
  }, [onSynced]);

  const statusColor =
    state === "synced" ? "text-green-500" :
    state === "behind" ? "text-yellow-500" :
    state === "ahead" ? "text-blue-500" :
    state === "diverged" ? "text-orange-500" :
    state === "error" ? "text-red-500" :
    "text-muted-foreground";

  const StatusIcon =
    state === "checking" || pulling ? Loader2Icon :
    state === "synced" ? CloudIcon :
    state === "error" ? CloudOffIcon :
    CloudIcon;

  return (
    <div className="flex flex-col shrink-0 border-b">
      <div className="flex items-center gap-1.5 px-2 py-1.5">
        <BranchStatus />
        <div className="flex-1" />

        <Tooltip content={detail || "Checking..."}>
          <div className={cn("flex items-center gap-1 text-[10px]", statusColor)}>
            <StatusIcon size={12} className={state === "checking" || pulling ? "animate-spin" : ""} />
            {state === "synced" && <span>Synced</span>}
            {state === "behind" && <span>{fetchInfo?.behind} behind</span>}
            {state === "ahead" && <span>{fetchInfo?.ahead} ahead</span>}
            {state === "diverged" && <span>Diverged</span>}
            {state === "error" && <span>Error</span>}
            {state === "no-remote" && <span>Local</span>}
          </div>
        </Tooltip>

        <Tooltip content="Fetch from remote">
          <button
            type="button"
            className="p-0.5 rounded hover:bg-muted/50 text-muted-foreground hover:text-foreground"
            onClick={checkStatus}
            disabled={state === "checking" || pulling}
          >
            <RefreshCwIcon size={12} />
          </button>
        </Tooltip>
      </div>

      {/* Behind banner — offer to pull */}
      {(state === "behind" || state === "diverged") && !pulling && (
        <div className="flex items-center gap-2 px-2 py-1.5 bg-yellow-500/10 border-t border-yellow-500/20">
          <CloudIcon size={12} className="text-yellow-500 shrink-0" />
          <span className="text-[11px] text-yellow-500 flex-1">{detail}</span>
          <Button
            variant="outline"
            size="xs"
            className="h-5 text-[10px] border-yellow-500/30 text-yellow-500 hover:bg-yellow-500/10"
            onClick={handlePull}
          >
            Pull
          </Button>
        </div>
      )}

      {/* Ahead banner — remind to push */}
      {state === "ahead" && (
        <div className="flex items-center gap-2 px-2 py-1.5 bg-blue-500/10 border-t border-blue-500/20">
          <CloudIcon size={12} className="text-blue-500 shrink-0" />
          <span className="text-[11px] text-blue-500 flex-1">{detail}</span>
        </div>
      )}

      {/* Error banner with fix option */}
      {state === "error" && !confirmingReset && (
        <div className="flex items-center gap-2 px-2 py-1.5 bg-red-500/10 border-t border-red-500/20">
          <CloudOffIcon size={12} className="text-red-500 shrink-0" />
          <span className="text-[11px] text-red-500 flex-1 truncate">{detail}</span>
          <Button
            variant="outline"
            size="xs"
            className="h-5 text-[10px] border-red-500/30 text-red-500 hover:bg-red-500/10 shrink-0"
            onClick={() => setConfirmingReset(true)}
          >
            Fix now
          </Button>
        </div>
      )}

      {/* Force reset confirmation */}
      {confirmingReset && (
        <div className="flex flex-col gap-1.5 px-2 py-2 bg-red-500/5 border-t border-red-500/20">
          <span className="text-[11px] text-red-400 font-medium">
            Are you sure? This will delete your local repo and re-clone from the remote. You will lose all un-pushed progress.
          </span>
          <div className="flex gap-1.5">
            <Button
              variant="destructive"
              size="xs"
              className="h-5 text-[10px]"
              onClick={handleForceReset}
              disabled={resetting}
            >
              {resetting ? <Loader2Icon size={10} className="animate-spin mr-1" /> : null}
              Yes, reset
            </Button>
            <Button
              variant="ghost"
              size="xs"
              className="h-5 text-[10px]"
              onClick={() => setConfirmingReset(false)}
            >
              Cancel
            </Button>
          </div>
        </div>
      )}
    </div>
  );
};
