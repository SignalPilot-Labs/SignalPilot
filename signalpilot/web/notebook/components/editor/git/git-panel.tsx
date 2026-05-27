import { spApiUrl } from "@/core/network/api";
import {
  CheckIcon,
  ChevronDownIcon,
  ChevronRightIcon,
  CloudIcon,
  CloudUploadIcon,
  FileIcon,
  FilePlusIcon,
  FileXIcon,
  GitBranchIcon,
  GitCommitVerticalIcon,
  Loader2Icon,
  PenLineIcon,
  RefreshCwIcon,
} from "lucide-react";
import React, { useCallback, useEffect, useRef, useState } from "react";
import { Button } from "@/components/ui/button";
import { Tooltip } from "@/components/ui/tooltip";
import { getGatewayProjectId } from "@/core/network/api";
import { getApiHeaders } from "@/core/network/api-headers";
import { BranchStatus } from "../chrome/wrapper/footer-items/branch-status";
import { cn } from "@/utils/cn";

interface GitFile { path: string; status: string; }
interface GitStatus { staged: GitFile[]; changed: GitFile[]; untracked: { path: string }[]; }
interface GitInfo {
  branch: string;
  last_commit: string;
  has_remote: boolean;
  ahead: number;
  behind: number;
  staged_count: number;
  changed_count: number;
  untracked_count: number;
  workspace: { exists: boolean; file_count: number; total_bytes: number; last_modified: number | null } | null;
}

async function fetchGitStatus(): Promise<GitStatus> {
  const resp = await fetch(spApiUrl("/git/status"), { method: "POST", headers: await getApiHeaders() });
  if (!resp.ok) {throw new Error("Failed");}
  return resp.json();
}

async function fetchGitInfo(): Promise<GitInfo | null> {
  try {
    const resp = await fetch(spApiUrl("/git/info"), { method: "POST", headers: await getApiHeaders() });
    if (!resp.ok) {return null;}
    return resp.json();
  } catch { return null; }
}

async function fetchDiff(file?: string): Promise<string> {
  try {
    const resp = await fetch(spApiUrl("/git/diff"), {
      method: "POST",
      headers: await getApiHeaders(),
      body: JSON.stringify({ file }),
    });
    if (!resp.ok) {return "";}
    const data = await resp.json() as { diff?: string };
    return data.diff || "";
  } catch { return ""; }
}

const STATUS_ICONS: Record<string, React.ReactNode> = {
  M: <PenLineIcon size={12} className="text-yellow-500" />,
  A: <FilePlusIcon size={12} className="text-green-500" />,
  D: <FileXIcon size={12} className="text-red-500" />,
  "?": <FilePlusIcon size={12} className="text-muted-foreground" />,
};

function timeAgoShort(ts: number | null): string {
  if (!ts) {return "never";}
  const secs = Math.floor(Date.now() / 1000 - ts);
  if (secs < 60) {return "just now";}
  if (secs < 3600) {return `${Math.floor(secs / 60)}m ago`;}
  if (secs < 86400) {return `${Math.floor(secs / 3600)}h ago`;}
  return `${Math.floor(secs / 86400)}d ago`;
}

function formatBytes(b: number): string {
  if (b < 1024) {return `${b} B`;}
  if (b < 1024 * 1024) {return `${(b / 1024).toFixed(1)} KB`;}
  return `${(b / 1024 / 1024).toFixed(1)} MB`;
}

export const GitPanel: React.FC = () => {
  const [status, setStatus] = useState<GitStatus | null>(null);
  const [info, setInfo] = useState<GitInfo | null>(null);
  const [loading, setLoading] = useState(false);
  const [commitMsg, setCommitMsg] = useState("");
  const [committing, setCommitting] = useState(false);
  const [message, setMessageRaw] = useState<{ type: "success" | "error"; text: string } | null>(null);
  const messageTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null);
  const setMessage = (msg: typeof message) => {
    if (messageTimerRef.current) {clearTimeout(messageTimerRef.current);}
    setMessageRaw(msg);
    if (msg) {messageTimerRef.current = setTimeout(() => setMessageRaw(null), 5000);}
  };
  const [stagedExpanded, setStagedExpanded] = useState(true);
  const [changedExpanded, setChangedExpanded] = useState(true);
  const [logExpanded, setLogExpanded] = useState(false);
  const [commits, setCommits] = useState<{ sha: string; full_sha?: string; message: string; location?: "local" | "remote" }[]>([]);
  const [selectedFile, setSelectedFile] = useState<string | null>(null);
  const [diffContent, setDiffContent] = useState("");
  const textareaRef = useRef<HTMLTextAreaElement>(null);

  const projectId = getGatewayProjectId();

  const fetchLog = useCallback(async () => {
    try {
      const resp = await fetch(spApiUrl("/git/log"), { method: "POST", headers: await getApiHeaders() });
      if (resp.ok) {
        const data = await resp.json() as { commits?: typeof commits };
        setCommits(data.commits ?? []);
      }
    } catch {}
  }, []);

  const refresh = useCallback(async () => {
    if (!projectId) {return;}
    setLoading(true);
    const [s, i] = await Promise.all([fetchGitStatus().catch(() => null), fetchGitInfo()]);
    if (s) {setStatus(s);}
    setInfo(i);
    fetchLog();
    setLoading(false);
  }, [projectId, fetchLog]);

  useEffect(() => { refresh(); }, [refresh]);

  // Load diff when file selected
  useEffect(() => {
    if (!selectedFile) { setDiffContent(""); return; }
    fetchDiff(selectedFile).then(setDiffContent);
  }, [selectedFile]);

  const stageFiles = async (paths: string[]) => {
    await fetch(spApiUrl("/git/stage"), { method: "POST", headers: await getApiHeaders(), body: JSON.stringify({ paths }) });
    refresh();
  };
  const stageAll = async () => {
    await fetch(spApiUrl("/git/stage"), { method: "POST", headers: await getApiHeaders(), body: JSON.stringify({ all: true }) });
    refresh();
  };
  const unstageFiles = async (paths: string[]) => {
    await fetch(spApiUrl("/git/unstage"), { method: "POST", headers: await getApiHeaders(), body: JSON.stringify({ paths }) });
    refresh();
  };
  const unstageAll = async () => {
    await fetch(spApiUrl("/git/unstage"), { method: "POST", headers: await getApiHeaders(), body: JSON.stringify({ all: true }) });
    refresh();
  };

  const handleCommitAndPush = async () => {
    if (!commitMsg.trim()) {return;}
    setCommitting(true);
    setMessage(null);
    try {
      const commitResp = await fetch(spApiUrl("/git/commit"), {
        method: "POST", headers: await getApiHeaders(),
        body: JSON.stringify({ message: commitMsg.trim() }),
      });
      const commitData = await commitResp.json() as { success: boolean; error?: string };
      if (!commitData.success) {
        setMessage({ type: "error", text: commitData.error || "Commit failed" });
        setCommitting(false);
        return;
      }
      setMessage({ type: "success", text: "Committed. Pushing..." });
      const pushResp = await fetch(spApiUrl("/git/push"), { method: "POST", headers: await getApiHeaders() });
      const pushData = await pushResp.json() as { success: boolean; error?: string };
      if (pushData.success) {
        setCommitMsg("");
        setMessage({ type: "success", text: "Pushed to remote" });
      } else {
        setMessage({ type: "error", text: pushData.error || "Push failed" });
      }
      refresh();
    } catch (e) {
      setMessage({ type: "error", text: String(e) });
    }
    setCommitting(false);
  };

  if (!projectId) {
    return (
      <div className="flex flex-col items-center justify-center h-full text-muted-foreground text-sm p-6 text-center gap-2">
        <GitBranchIcon className="h-8 w-8 opacity-30" />
        <p>No cloud project active</p>
      </div>
    );
  }

  const allChanges = [
    ...(status?.changed || []),
    ...(status?.untracked || []).map((u) => ({ path: u.path, status: "?" })),
  ];
  const stagedFiles = status?.staged || [];
  const hasChanges = allChanges.length > 0 || stagedFiles.length > 0;

  return (
    <div className="flex flex-col h-full overflow-hidden text-sm">
      {/* Info header */}
      <div className="px-3 py-2 border-b shrink-0 space-y-1.5">
        <div className="flex items-center gap-2">
          <BranchStatus />
          <div className="flex-1" />
          <Tooltip content="Refresh">
            <button type="button" className="p-1 rounded hover:bg-muted/50 text-muted-foreground hover:text-foreground"
              onClick={refresh} disabled={loading}>
              <RefreshCwIcon size={14} className={loading ? "animate-spin" : ""} />
            </button>
          </Tooltip>
        </div>

        {info && (
          <div className="space-y-1 text-[10px] text-muted-foreground">
            {/* Last commit */}
            <div className="flex items-center gap-1.5">
              <GitCommitVerticalIcon size={10} />
              <span className="truncate">{info.last_commit || "No commits"}</span>
            </div>

            {/* Ahead/behind */}
            {info.has_remote && (info.ahead > 0 || info.behind > 0) && (
              <div className="flex items-center gap-2">
                {info.ahead > 0 && (
                  <span className="text-blue-500">{info.ahead} ahead</span>
                )}
                {info.behind > 0 && (
                  <span className="text-yellow-500">{info.behind} behind</span>
                )}
              </div>
            )}
            {info.has_remote && info.ahead === 0 && info.behind === 0 && (
              <div className="text-green-500 flex items-center gap-1">
                <CheckIcon size={10} />
                Up to date with remote
              </div>
            )}

            {/* Workspace status */}
            {info.workspace && (
              <div className="flex items-center gap-1.5 pt-0.5 border-t border-border/50">
                <CloudIcon size={10} />
                {info.workspace.exists ? (
                  <span>
                    Workspace: {info.workspace.file_count} files ({formatBytes(info.workspace.total_bytes)})
                    {info.workspace.last_modified && (
                      <span className="opacity-60"> synced {timeAgoShort(info.workspace.last_modified)}</span>
                    )}
                  </span>
                ) : (
                  <span className="opacity-60">No workspace backup</span>
                )}
              </div>
            )}

            {/* Change summary */}
            {hasChanges && (
              <div className="flex items-center gap-2 pt-0.5">
                {stagedFiles.length > 0 && (
                  <span className="text-green-500">{stagedFiles.length} staged</span>
                )}
                {allChanges.length > 0 && (
                  <span className="text-yellow-500">{allChanges.length} changed</span>
                )}
              </div>
            )}
          </div>
        )}
      </div>

      {/* Commit area */}
      <div className="px-3 py-2 border-b shrink-0 space-y-2">
        <textarea
          ref={textareaRef}
          value={commitMsg}
          onChange={(e) => setCommitMsg(e.target.value)}
          placeholder="Commit message..."
          rows={2}
          className={cn(
            "w-full rounded-md border border-border bg-background px-2.5 py-1.5 text-xs",
            "placeholder:text-muted-foreground/50 resize-none",
            "focus:outline-none focus:ring-1 focus:ring-primary/40",
          )}
          onKeyDown={(e) => {
            if (e.key === "Enter" && (e.ctrlKey || e.metaKey)) {handleCommitAndPush();}
          }}
        />
        <Button
          variant="default" size="sm" className="w-full text-xs h-7"
          onClick={handleCommitAndPush}
          disabled={!commitMsg.trim() || stagedFiles.length === 0 || committing}
        >
          {committing ? <Loader2Icon size={12} className="animate-spin mr-1" />
            : <CloudUploadIcon size={12} className="mr-1" />}
          Commit & Push
        </Button>
      </div>

      {/* Status message */}
      {message && (
        <div className={cn(
          "px-3 py-1.5 text-[11px] border-b",
          message.type === "success" ? "bg-green-500/10 text-green-500" : "bg-red-500/10 text-red-500",
        )}>
          {message.text}
        </div>
      )}

      {/* File lists + diff viewer */}
      <div className="flex-1 overflow-y-auto">
        {loading && !status ? (
          <div className="flex items-center justify-center py-8 text-muted-foreground text-xs">
            <Loader2Icon size={14} className="animate-spin mr-2" />Loading...
          </div>
        ) : !hasChanges ? (
          <div className="flex flex-col items-center justify-center py-8 text-muted-foreground text-xs gap-1">
            <CheckIcon size={16} className="opacity-40" />
            <span>Working tree clean</span>
          </div>
        ) : (
          <>
            {stagedFiles.length > 0 && (
              <FileSection title="Staged Changes" count={stagedFiles.length}
                expanded={stagedExpanded} onToggle={() => setStagedExpanded(!stagedExpanded)}
                allChecked={true} onToggleAll={unstageAll}>
                {stagedFiles.map((f) => (
                  <FileRow key={f.path} path={f.path} status={f.status} checked={true}
                    onToggleCheck={() => unstageFiles([f.path])}
                    selected={selectedFile === f.path}
                    onSelect={() => setSelectedFile(selectedFile === f.path ? null : f.path)} />
                ))}
              </FileSection>
            )}

            {allChanges.length > 0 && (
              <FileSection title="Changes" count={allChanges.length}
                expanded={changedExpanded} onToggle={() => setChangedExpanded(!changedExpanded)}
                allChecked={false} onToggleAll={stageAll}>
                {allChanges.map((f) => (
                  <FileRow key={f.path} path={f.path} status={f.status} checked={false}
                    onToggleCheck={() => stageFiles([f.path])}
                    selected={selectedFile === f.path}
                    onSelect={() => setSelectedFile(selectedFile === f.path ? null : f.path)} />
                ))}
              </FileSection>
            )}
          </>
        )}

        {/* Inline diff viewer */}
        {selectedFile && diffContent && (
          <div className="border-t">
            <div className="px-2 py-1 text-[10px] font-semibold text-muted-foreground uppercase tracking-wider bg-muted/30">
              Diff: {selectedFile}
            </div>
            <pre className="text-[10px] leading-[16px] font-mono overflow-x-auto p-2 max-h-[300px] overflow-y-auto">
              {diffContent.split("\n").map((line, i) => {
                let color = "text-muted-foreground";
                if (line.startsWith("+") && !line.startsWith("+++")) {color = "text-green-400";}
                else if (line.startsWith("-") && !line.startsWith("---")) {color = "text-red-400";}
                else if (line.startsWith("@@")) {color = "text-blue-400";}
                return <div key={i} className={color}>{line || " "}</div>;
              })}
            </pre>
          </div>
        )}

        {/* Commit log */}
        {commits.length > 0 && (
          <div className="border-t mt-1">
            <div className="flex items-center gap-1.5 px-2 py-1 text-[11px] font-semibold uppercase tracking-wider text-muted-foreground cursor-pointer hover:bg-muted/30"
              onClick={() => setLogExpanded(!logExpanded)}>
              {logExpanded ? <ChevronDownIcon size={12} /> : <ChevronRightIcon size={12} />}
              <span className="flex-1">Commit Log</span>
              <span className="text-[10px] font-mono">{commits.length}</span>
            </div>
            {logExpanded && commits.map((c, i) => {
              const showSyncStatus = info?.has_remote;
              const isLocal = showSyncStatus && c.location === "local";
              const isRemoteBoundary = isLocal && commits[i + 1]?.location !== "local";
              return (
                <React.Fragment key={c.sha}>
                  <div className="flex items-center gap-1.5 px-3 py-0.5 text-xs hover:bg-muted/30">
                    <GitCommitVerticalIcon size={10} className={isLocal ? "text-amber-500" : showSyncStatus ? "text-green-500" : "text-primary"} />
                    <span className="font-mono text-[10px] text-primary shrink-0">{c.sha}</span>
                    <span className="truncate text-muted-foreground flex-1">{c.message}</span>
                    {showSyncStatus && (isLocal ? (
                      <span className="text-[9px] px-1 rounded bg-amber-500/10 text-amber-500 shrink-0">local</span>
                    ) : (
                      <span className="text-[9px] px-1 rounded bg-green-500/10 text-green-500 shrink-0">pushed</span>
                    ))}
                  </div>
                  {isRemoteBoundary && (
                    <div className="flex items-center gap-2 px-3 py-0.5">
                      <div className="flex-1 border-t border-dashed border-green-500/30" />
                      <span className="text-[9px] text-green-500/60 flex items-center gap-1">
                        <CloudIcon size={9} />
                        origin/{info?.branch || "main"}
                      </span>
                      <div className="flex-1 border-t border-dashed border-green-500/30" />
                    </div>
                  )}
                </React.Fragment>
              );
            })}
          </div>
        )}
      </div>
    </div>
  );
};

// ── Sub-components ──────────────────────────────────────────────

const FileSection: React.FC<{
  title: string; count: number; expanded: boolean; onToggle: () => void;
  allChecked: boolean; onToggleAll: () => void; children: React.ReactNode;
}> = ({ title, count, expanded, onToggle, allChecked, onToggleAll, children }) => (
  <div>
    <div className="flex items-center gap-1.5 px-2 py-1 text-[11px] font-semibold uppercase tracking-wider text-muted-foreground cursor-pointer hover:bg-muted/30" onClick={onToggle}>
      <span onClick={(e) => e.stopPropagation()}>
        <input type="checkbox" checked={allChecked} onChange={onToggleAll}
          className="w-3 h-3 rounded border-border accent-primary cursor-pointer" />
      </span>
      {expanded ? <ChevronDownIcon size={12} /> : <ChevronRightIcon size={12} />}
      <span className="flex-1">{title}</span>
      <span className="text-[10px] font-mono">{count}</span>
    </div>
    {expanded && children}
  </div>
);

const FileRow: React.FC<{
  path: string; status: string; checked: boolean;
  onToggleCheck: () => void; selected: boolean; onSelect: () => void;
}> = ({ path, status, checked, onToggleCheck, selected, onSelect }) => {
  const filename = path.split("/").pop() || path;
  const dir = path.includes("/") ? path.slice(0, path.lastIndexOf("/")) : "";

  return (
    <div className={cn(
      "flex items-center gap-1.5 px-3 py-0.5 text-xs hover:bg-muted/30 group cursor-pointer",
      selected && "bg-primary/10",
    )} onClick={onSelect}>
      <input type="checkbox" checked={checked} onChange={(e) => { e.stopPropagation(); onToggleCheck(); }}
        className="w-3 h-3 rounded border-border accent-primary cursor-pointer shrink-0" />
      {STATUS_ICONS[status] || <FileIcon size={12} className="text-muted-foreground" />}
      <span className="flex-1 truncate min-w-0" title={path}>
        <span className="text-foreground">{filename}</span>
        {dir && <span className="text-muted-foreground ml-1">{dir}</span>}
      </span>
      <span className="text-[10px] font-mono text-muted-foreground w-3 text-center">{status}</span>
    </div>
  );
};

export default GitPanel;
