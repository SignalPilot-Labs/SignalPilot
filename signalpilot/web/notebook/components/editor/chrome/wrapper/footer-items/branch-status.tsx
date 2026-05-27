import { spApiUrl } from "@/core/network/api";
import { useAtom } from "jotai";
import {
  CheckIcon,
  CloudIcon,
  CloudOffIcon,
  GitBranchIcon,
  Loader2Icon,
  PlusIcon,
  RefreshCwIcon,
} from "lucide-react";
import React, { useCallback, useEffect, useRef, useState } from "react";
import { createPortal } from "react-dom";
import { Button } from "@/components/ui/button";
import { Tooltip } from "@/components/ui/tooltip";
import { getGatewayProjectId } from "@/core/network/api";
import { getApiHeaders } from "@/core/network/api-headers";
import {
  branchListAtom,
  createBranch,
  fetchBranches,
  gatewayBranchIdAtom,
  hasUncommittedChanges,
  switchBranch,
} from "@/core/branch/branch-state";
import { cn } from "@/utils/cn";
import { treeAtom } from "@/components/editor/file-tree/state";
import { store } from "@/core/state/jotai";
import { usePortalContainer } from "@/embed/portal-container";
import { rebootMountConfig } from "@/core/bootstrap/reboot-mount";
import { toast } from "@/components/ui/use-toast";

type SyncStatus = "unknown" | "syncing" | "synced" | "error";


export const BranchStatus: React.FC = () => {
  const [branchId, setBranchId] = useAtom(gatewayBranchIdAtom);
  const [branches, setBranches] = useAtom(branchListAtom);
  const [open, setOpen] = useState(false);
  const [creating, setCreating] = useState(false);
  const [newBranchName, setNewBranchName] = useState("");
  const [loading, setLoading] = useState(false);
  const [syncStatus, setSyncStatus] = useState<SyncStatus>("unknown");
  const [syncDetail, setSyncDetail] = useState("");
  const popoverRef = useRef<HTMLDivElement>(null);
  const triggerRef = useRef<HTMLButtonElement>(null);
  const inputRef = useRef<HTMLInputElement>(null);
  const portalContainer = usePortalContainer();

  const projectId = getGatewayProjectId();
  if (!projectId) {return null;}

  const currentBranch = branchId || "main";

  // Check sync status on mount and every 5 minutes
  const checkSyncStatus = useCallback(() => {
    getApiHeaders().then((hdrs) =>
      fetch(spApiUrl("/project/sync-status"), {
        method: "POST",
        headers: hdrs,
      })
    )
      .then((r) => r.json() as Promise<{ synced: boolean; file_count: number }>)
      .then((data) => {
        if (data.synced) {
          setSyncStatus("synced");
          setSyncDetail(`${data.file_count} files synced`);
        } else {
          setSyncStatus("unknown");
          setSyncDetail("Not synced");
        }
      })
      .catch(() => {
        setSyncStatus("error");
        setSyncDetail("Failed to check sync status");
      });
  }, []);

  useEffect(() => {
    checkSyncStatus();
    const interval = setInterval(checkSyncStatus, 5 * 60 * 1000);
    return () => clearInterval(interval);
  }, [branchId, checkSyncStatus]);

  const handleSync = useCallback(async () => {
    setSyncStatus("syncing");
    setSyncDetail("Syncing...");
    try {
      const resp = await fetch(spApiUrl("/project/sync-down"), {
        method: "POST",
        headers: await getApiHeaders(),
      });
      const result = await resp.json() as { local_dir?: string; file_count?: number; error?: string };
      if (result.local_dir) {
        setSyncStatus("synced");
        setSyncDetail(`${result.file_count} files synced`);
        store.get(treeAtom).refresh([]);
      } else {
        setSyncStatus("error");
        setSyncDetail(result.error || "Sync failed");
      }
    } catch (e) {
      setSyncStatus("error");
      setSyncDetail(String(e));
    }
  }, []);

  const loadBranches = useCallback(async () => {
    setLoading(true);
    const list = await fetchBranches();
    setBranches(list);
    setLoading(false);
  }, [setBranches]);

  useEffect(() => {
    if (open) {loadBranches();}
  }, [open, loadBranches]);

  useEffect(() => {
    if (creating && inputRef.current) {inputRef.current.focus();}
  }, [creating]);

  useEffect(() => {
    if (!open) {return;}
    const handler = (e: MouseEvent) => {
      if (popoverRef.current && !popoverRef.current.contains(e.target as Node)) {
        setOpen(false);
        setCreating(false);
        setNewBranchName("");
      }
    };
    document.addEventListener("mousedown", handler);
    return () => document.removeEventListener("mousedown", handler);
  }, [open]);

  const [switchTarget, setSwitchTarget] = useState<string | null>(null);
  const [dirtyFiles, setDirtyFiles] = useState<string[]>([]);

  const handleSwitch = async (name: string) => {
    if (name === currentBranch) {return;}
    const dirty = await hasUncommittedChanges();
    if (dirty && dirty.length > 0) {
      setDirtyFiles(dirty);
      setSwitchTarget(name);
      return;
    }
    void doSwitch(name);
  };

  const doSwitch = async (name: string) => {
    setSwitchTarget(null);
    setDirtyFiles([]);
    await switchBranch(name);
    setBranchId(name);
    setOpen(false);
    const params = new URLSearchParams(window.location.search);
    params.set("branch", name);
    try {
      await rebootMountConfig({ searchParams: params });
    } catch (err) {
      toast({
        title: "Branch switch failed",
        description: err instanceof Error ? err.message : String(err),
        variant: "danger",
      });
    }
  };

  const handleCreate = async () => {
    const name = newBranchName.trim().replace(/[^a-zA-Z0-9_-]/g, "-");
    if (!name) {return;}
    setLoading(true);
    const ok = await createBranch(name);
    if (ok) {
      await switchBranch(name);
      setBranchId(name);
      setOpen(false);
      setCreating(false);
      setNewBranchName("");
      const params = new URLSearchParams(window.location.search);
      params.set("branch", name);
      try {
        await rebootMountConfig({ searchParams: params });
      } catch (err) {
        toast({
          title: "Branch switch failed",
          description: err instanceof Error ? err.message : String(err),
          variant: "danger",
        });
      }
    }
    setLoading(false);
  };

  const SyncIcon =
    syncStatus === "syncing" ? Loader2Icon :
    syncStatus === "synced" ? CloudIcon :
    syncStatus === "error" ? CloudOffIcon :
    CloudOffIcon;

  const syncColor =
    syncStatus === "synced" ? "text-green-500" :
    syncStatus === "syncing" ? "text-yellow-500 animate-spin" :
    syncStatus === "error" ? "text-red-500" :
    "text-muted-foreground";

  const getPopoverStyle = (): React.CSSProperties => {
    if (!triggerRef.current) {return {};}
    const rect = triggerRef.current.getBoundingClientRect();
    const spaceBelow = window.innerHeight - rect.bottom;
    const spaceAbove = rect.top;
    const openDown = spaceBelow > 300 || spaceBelow > spaceAbove;
    return {
      position: "fixed",
      left: rect.left,
      ...(openDown
        ? { top: rect.bottom + 8 }
        : { bottom: window.innerHeight - rect.top + 8 }),
      width: 280,
    };
  };

  return (
    <div className="flex items-center gap-0.5">
      {/* Sync status + button */}
      <Tooltip content={syncDetail || "Sync status"} side="top" delayDuration={200}>
        <button
          type="button"
          className={cn(
            "flex items-center gap-1 px-1.5 py-1 text-xs cursor-pointer rounded",
            "hover:bg-(--sage-3)",
          )}
          onClick={handleSync}
          disabled={syncStatus === "syncing"}
        >
          <SyncIcon className={cn("w-3 h-3", syncColor)} />
        </button>
      </Tooltip>

      {/* Branch name + switcher */}
      <Tooltip content="Switch branch" side="top" delayDuration={200}>
        <button
          ref={triggerRef}
          type="button"
          className={cn(
            "h-full flex items-center gap-1.5 px-2 py-1 text-xs font-mono cursor-pointer rounded",
            "hover:bg-(--sage-3) text-muted-foreground hover:text-foreground",
            open && "bg-(--sage-4) text-foreground",
          )}
          onClick={() => setOpen(!open)}
        >
          <GitBranchIcon className="w-3.5 h-3.5 text-primary" />
          <span className="max-w-[120px] truncate">{currentBranch}</span>
        </button>
      </Tooltip>

      {open && createPortal(
        <div
          ref={popoverRef}
          style={getPopoverStyle()}
          className={cn(
            "rounded-lg border border-border bg-popover shadow-lg",
            "z-[9999] overflow-hidden",
          )}
        >
          <div className="px-3 py-2 border-b border-border flex items-center justify-between">
            <div className="text-[10px] uppercase tracking-wider font-semibold text-muted-foreground">
              Branches
            </div>
            <Tooltip content="Sync from cloud" side="top">
              <button
                type="button"
                className="p-1 rounded hover:bg-muted/50 text-muted-foreground hover:text-foreground"
                onClick={handleSync}
                disabled={syncStatus === "syncing"}
              >
                <RefreshCwIcon size={12} className={syncStatus === "syncing" ? "animate-spin" : ""} />
              </button>
            </Tooltip>
          </div>

          <div className="max-h-[240px] overflow-y-auto py-1">
            {loading && branches.length === 0 ? (
              <div className="flex items-center justify-center py-4 text-muted-foreground text-xs">
                <Loader2Icon size={14} className="animate-spin mr-2" />
                Loading...
              </div>
            ) : (
              branches.filter((b) => !b.name.startsWith("signalpilot-agent/")).map((b) => (
                <button
                  key={b.name}
                  type="button"
                  className={cn(
                    "w-full flex items-center gap-2 px-3 py-1.5 text-xs text-left",
                    "hover:bg-muted/50 cursor-pointer",
                    b.name === currentBranch && "text-primary font-medium",
                  )}
                  onClick={() => handleSwitch(b.name)}
                >
                  <GitBranchIcon size={12} className="shrink-0" />
                  <span className="flex-1 truncate">{b.name}</span>
                  {b.is_agent && (
                    <span className="text-[9px] px-1 rounded bg-purple-500/10 text-purple-500">
                      agent
                    </span>
                  )}
                  {b.is_remote && !b.is_local && (
                    <span className="text-[9px] px-1 rounded bg-blue-500/10 text-blue-500">
                      remote
                    </span>
                  )}
                  {b.sha && (
                    <span className="text-[9px] font-mono text-muted-foreground">{b.sha}</span>
                  )}
                  {b.name === currentBranch && (
                    <CheckIcon size={12} className="shrink-0 text-primary" />
                  )}
                </button>
              ))
            )}
          </div>

          <div className="border-t border-border px-2 py-2">
            {creating ? (
              <div className="flex items-center gap-1.5">
                <input
                  ref={inputRef}
                  type="text"
                  value={newBranchName}
                  onChange={(e) => setNewBranchName(e.target.value)}
                  onKeyDown={(e) => {
                    if (e.key === "Enter") {handleCreate();}
                    if (e.key === "Escape") {
                      setCreating(false);
                      setNewBranchName("");
                    }
                  }}
                  placeholder="branch-name"
                  className="flex-1 rounded border border-border bg-background px-2 py-1 text-xs font-mono placeholder:text-muted-foreground/50 focus:outline-none focus:ring-1 focus:ring-primary/40"
                />
                <Button
                  variant="default"
                  size="xs"
                  onClick={handleCreate}
                  disabled={!newBranchName.trim() || loading}
                  className="h-6 text-[10px]"
                >
                  {loading ? <Loader2Icon size={10} className="animate-spin" /> : "Create"}
                </Button>
              </div>
            ) : (
              <button
                type="button"
                className="w-full flex items-center gap-2 px-1 py-1 text-xs text-muted-foreground hover:text-foreground cursor-pointer rounded hover:bg-muted/50"
                onClick={() => setCreating(true)}
              >
                <PlusIcon size={12} />
                Create branch from {currentBranch}
              </button>
            )}
          </div>

          {/* Dirty files warning before branch switch */}
          {switchTarget && dirtyFiles.length > 0 && (
            <div className="border-t border-red-500/20 bg-red-500/5 px-3 py-2 space-y-2">
              <div className="text-[11px] text-red-400 font-medium">
                Switch to "{switchTarget}"? These uncommitted changes will be lost:
              </div>
              <div className="max-h-[100px] overflow-y-auto space-y-0.5">
                {dirtyFiles.map((f) => (
                  <div key={f} className="text-[10px] font-mono text-red-400/80 truncate">
                    {f}
                  </div>
                ))}
              </div>
              <div className="flex gap-1.5">
                <Button
                  variant="destructive"
                  size="xs"
                  className="h-5 text-[10px]"
                  onClick={() => doSwitch(switchTarget)}
                >
                  Discard & switch
                </Button>
                <Button
                  variant="ghost"
                  size="xs"
                  className="h-5 text-[10px]"
                  onClick={() => { setSwitchTarget(null); setDirtyFiles([]); }}
                >
                  Cancel
                </Button>
              </div>
            </div>
          )}
        </div>,
        portalContainer ?? document.body,
      )}
    </div>
  );
};
