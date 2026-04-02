"use client";

import { useState, useMemo, useEffect } from "react";
import { motion, AnimatePresence } from "framer-motion";
import { clsx } from "clsx";
import type { FeedEvent, FileChange } from "@/lib/types";
import type { DiffFile, DiffStats } from "@/lib/api";
import { fetchRunDiff } from "@/lib/api";
import { getToolCategory } from "@/lib/types";

/* ── Extract file changes from tool call events (live) ── */
function extractFileChanges(events: FeedEvent[]): FileChange[] {
  const changes: FileChange[] = [];
  for (const ev of events) {
    if (ev._kind !== "tool") continue;
    const tc = ev.data;
    const cat = getToolCategory(tc.tool_name);
    const input = tc.input_data || {};
    const output = tc.output_data || {};

    switch (cat) {
      case "read": {
        const fileObj = (output as Record<string, unknown>)?.file as Record<string, unknown> | undefined;
        const fp = (input.file_path as string) || (fileObj?.filePath as string) || "";
        if (fp) changes.push({ path: norm(fp), action: "read", timestamp: tc.ts, toolCallId: tc.id, toolName: tc.tool_name });
        break;
      }
      case "write": {
        const fp = (input.file_path as string) || (output.filePath as string) || "";
        if (fp) {
          const patch = output.structuredPatch as Array<Record<string, unknown>> | undefined;
          let added = 0;
          if (patch) for (const h of patch) added += (h.newLines as number) || 0;
          changes.push({ path: norm(fp), action: "write", linesAdded: added || undefined, timestamp: tc.ts, toolCallId: tc.id, toolName: tc.tool_name });
        }
        break;
      }
      case "edit": {
        const fp = (input.file_path as string) || (output.filePath as string) || "";
        if (fp) {
          const patch = output.structuredPatch as Array<Record<string, unknown>> | undefined;
          let added = 0, removed = 0;
          if (patch) for (const h of patch) for (const l of ((h.lines as string[]) || [])) {
            if (l.startsWith("+") && !l.startsWith("+++")) added++;
            if (l.startsWith("-") && !l.startsWith("---")) removed++;
          }
          changes.push({ path: norm(fp), action: "edit", linesAdded: added || undefined, linesRemoved: removed || undefined, timestamp: tc.ts, toolCallId: tc.id, toolName: tc.tool_name });
        }
        break;
      }
    }
  }
  return changes;
}

function norm(p: string): string {
  return p.replace(/^\/home\/agentuser\/repo\//, "").replace(/^\/workspace\//, "").replace(/^\/home\/agentuser\//, "~/");
}

/* ── Tree node ── */
interface TreeNode {
  name: string;
  fullPath: string;
  isDir: boolean;
  children: Map<string, TreeNode>;
  added: number;
  removed: number;
  status?: string;
}

function buildTreeFromDiff(files: DiffFile[]): TreeNode {
  const root: TreeNode = { name: "", fullPath: "", isDir: true, children: new Map(), added: 0, removed: 0 };
  for (const f of files) {
    const parts = f.path.split("/").filter(Boolean);
    let cur = root;
    for (let i = 0; i < parts.length; i++) {
      const part = parts[i];
      const isLast = i === parts.length - 1;
      if (!cur.children.has(part)) {
        cur.children.set(part, { name: part, fullPath: parts.slice(0, i + 1).join("/"), isDir: !isLast, children: new Map(), added: 0, removed: 0 });
      }
      cur = cur.children.get(part)!;
      if (isLast) {
        cur.added = f.added;
        cur.removed = f.removed;
        cur.status = f.status;
      }
    }
  }
  return root;
}

function buildTreeFromChanges(changes: FileChange[]): TreeNode {
  const root: TreeNode = { name: "", fullPath: "", isDir: true, children: new Map(), added: 0, removed: 0 };
  const seen = new Map<string, { added: number; removed: number }>();
  for (const c of changes) {
    if (c.action === "read") continue;
    const key = c.path;
    const existing = seen.get(key) || { added: 0, removed: 0 };
    existing.added += c.linesAdded || 0;
    existing.removed += c.linesRemoved || 0;
    seen.set(key, existing);
  }
  for (const [path, stats] of seen) {
    const parts = path.split("/").filter(Boolean);
    let cur = root;
    for (let i = 0; i < parts.length; i++) {
      const part = parts[i];
      const isLast = i === parts.length - 1;
      if (!cur.children.has(part)) {
        cur.children.set(part, { name: part, fullPath: parts.slice(0, i + 1).join("/"), isDir: !isLast, children: new Map(), added: 0, removed: 0 });
      }
      cur = cur.children.get(part)!;
      if (isLast) { cur.added = stats.added; cur.removed = stats.removed; cur.status = "modified"; }
    }
  }
  return root;
}

/* ── Icons ── */
function FileIcon({ name, status }: { name: string; status?: string }) {
  const ext = name.split(".").pop()?.toLowerCase() || "";
  let color = "#555";
  if (status === "added") color = "#00ff88";
  else if (status === "deleted") color = "#ff4444";
  else if (status === "modified") color = "#ffcc44";
  else if (ext === "tsx" || ext === "ts") color = "#3178c6";
  else if (ext === "css") color = "#264de4";
  else if (ext === "py") color = "#3776ab";
  else if (ext === "sql") color = "#e38c00";

  return (
    <svg width="12" height="12" viewBox="0 0 12 12" fill="none" stroke={color} strokeWidth="1" strokeLinecap="round">
      <path d="M3 1.5h4.5l2.5 2.5v6.5a1 1 0 01-1 1H3a1 1 0 01-1-1v-8a1 1 0 011-1z" />
      <polyline points="7.5 1.5 7.5 4 10 4" />
    </svg>
  );
}

function DirIcon({ open }: { open: boolean }) {
  return (
    <svg width="12" height="12" viewBox="0 0 12 12" fill="none" stroke="#555" strokeWidth="1" strokeLinecap="round">
      {open
        ? <><path d="M1 3.5h3l1-1h4.5a1 1 0 011 1V4H2.5L1 9V3.5z" /><path d="M2.5 4L1 9h8.5l1.5-5H2.5z" /></>
        : <path d="M1 3h3l1 1h5a1 1 0 011 1v5a1 1 0 01-1 1H2a1 1 0 01-1-1V3z" />}
    </svg>
  );
}

/* ── Tree Node Component ── */
function NodeItem({ node, depth }: { node: TreeNode; depth: number }) {
  const [open, setOpen] = useState(depth < 2);
  const isDir = node.isDir && node.children.size > 0;

  const sorted = useMemo(() => {
    const arr = Array.from(node.children.values());
    return arr.sort((a, b) => {
      if (a.isDir && !b.isDir) return -1;
      if (!a.isDir && b.isDir) return 1;
      return a.name.localeCompare(b.name);
    });
  }, [node.children]);

  // Aggregate child stats for directories
  const totalAdded = useMemo(() => {
    if (!node.isDir) return node.added;
    let sum = node.added;
    const walk = (n: TreeNode) => { sum += n.added; n.children.forEach(walk); };
    node.children.forEach(walk);
    return sum;
  }, [node]);
  const totalRemoved = useMemo(() => {
    if (!node.isDir) return node.removed;
    let sum = node.removed;
    const walk = (n: TreeNode) => { sum += n.removed; n.children.forEach(walk); };
    node.children.forEach(walk);
    return sum;
  }, [node]);

  return (
    <div>
      <div
        className={clsx(
          "flex items-center gap-1.5 py-[3px] px-1 rounded cursor-pointer transition-colors text-[10px]",
          "hover:bg-white/[0.03]",
          node.status === "added" && "bg-[#00ff88]/[0.02]",
          node.status === "deleted" && "bg-[#ff4444]/[0.02]",
        )}
        style={{ paddingLeft: depth * 14 + 4 }}
        onClick={() => isDir && setOpen(!open)}
      >
        {isDir ? (
          <svg width="8" height="8" viewBox="0 0 8 8" fill="none" stroke="#888" strokeWidth="1.5" strokeLinecap="round"
            className={clsx("shrink-0 transition-transform duration-150", open && "rotate-90")}>
            <polyline points="2 1 6 4 2 7" />
          </svg>
        ) : <span className="w-2 shrink-0" />}

        {isDir ? <DirIcon open={open} /> : <FileIcon name={node.name} status={node.status} />}

        <span className={clsx("flex-1 truncate", node.status === "deleted" ? "text-[#ff4444]/80 line-through" : node.status === "added" ? "text-[#00ff88]" : "text-[#bbb]")}>
          {node.name}
        </span>

        {(totalAdded > 0 || totalRemoved > 0) && (
          <span className="flex items-center gap-1 shrink-0">
            {totalAdded > 0 && <span className="text-[9px] text-[#00ff88]/70 tabular-nums">+{totalAdded}</span>}
            {totalRemoved > 0 && <span className="text-[9px] text-[#ff4444]/70 tabular-nums">-{totalRemoved}</span>}
          </span>
        )}

        {node.status && !node.isDir && (
          <span className={clsx(
            "text-[8px] font-bold uppercase tracking-wider rounded px-1 py-0.5 shrink-0",
            node.status === "added" && "text-[#00ff88]/80 bg-[#00ff88]/10",
            node.status === "modified" && "text-[#ffcc44]/80 bg-[#ffcc44]/10",
            node.status === "deleted" && "text-[#ff4444]/80 bg-[#ff4444]/10",
            node.status === "renamed" && "text-[#88ccff]/80 bg-[#88ccff]/10",
          )}>
            {node.status === "added" ? "A" : node.status === "modified" ? "M" : node.status === "deleted" ? "D" : "R"}
          </span>
        )}
      </div>

      <AnimatePresence>
        {open && isDir && (
          <motion.div initial={{ height: 0, opacity: 0 }} animate={{ height: "auto", opacity: 1 }} exit={{ height: 0, opacity: 0 }} transition={{ duration: 0.15 }} className="overflow-hidden">
            {sorted.map(child => <NodeItem key={child.fullPath} node={child} depth={depth + 1} />)}
          </motion.div>
        )}
      </AnimatePresence>
    </div>
  );
}

/* ── File List (flat view) ── */
function FileList({ files }: { files: DiffFile[] }) {
  const sorted = [...files].sort((a, b) => (b.added + b.removed) - (a.added + a.removed));
  return (
    <div className="space-y-0.5">
      {sorted.map((f, i) => (
        <div key={i} className="flex items-center gap-1.5 px-2 py-[3px] text-[10px] hover:bg-white/[0.02] rounded transition-colors">
          <span className={clsx(
            "shrink-0 w-[14px] text-center text-[8px] font-bold uppercase",
            f.status === "added" && "text-[#00ff88]/80",
            f.status === "modified" && "text-[#ffcc44]/80",
            f.status === "deleted" && "text-[#ff4444]/80",
            f.status === "renamed" && "text-[#88ccff]/80",
          )}>
            {f.status?.[0]?.toUpperCase() || "M"}
          </span>
          <span className="text-[#aaa] truncate flex-1">{f.path}</span>
          {f.added > 0 && <span className="text-[#00ff88]/70 tabular-nums shrink-0">+{f.added}</span>}
          {f.removed > 0 && <span className="text-[#ff4444]/70 tabular-nums shrink-0">-{f.removed}</span>}
        </div>
      ))}
    </div>
  );
}

/* ── Main WorkTree Panel ── */
export function WorkTree({ events, runId }: { events: FeedEvent[]; runId: string | null }) {
  const [activeTab, setActiveTab] = useState<"tree" | "files" | "live">("tree");
  const [collapsed, setCollapsed] = useState(false);
  const [diffData, setDiffData] = useState<DiffStats | null>(null);
  const [diffLoading, setDiffLoading] = useState(false);

  // Fetch git diff when run changes — clear stale data immediately
  useEffect(() => {
    setDiffData(null);
    if (!runId) return;
    setDiffLoading(true);
    fetchRunDiff(runId).then(d => { setDiffData(d); setDiffLoading(false); }).catch(() => setDiffLoading(false));
  }, [runId]);

  // Also refresh periodically for live runs
  useEffect(() => {
    if (!runId || !diffData || diffData.source !== "live") return;
    const id = setInterval(() => {
      fetchRunDiff(runId).then(setDiffData).catch(() => {});
    }, 15000);
    return () => clearInterval(id);
  }, [runId, diffData?.source]);

  // Live changes from event stream
  const liveChanges = useMemo(() => extractFileChanges(events), [events]);
  const liveTree = useMemo(() => buildTreeFromChanges(liveChanges), [liveChanges]);

  // Git diff tree
  const diffTree = useMemo(() => diffData?.files ? buildTreeFromDiff(diffData.files) : null, [diffData]);

  const hasGitDiff = diffData && diffData.files && diffData.files.length > 0;
  const hasLive = liveChanges.filter(c => c.action !== "read").length > 0;

  const totalFiles = diffData?.total_files || 0;
  const totalAdded = diffData?.total_added || 0;
  const totalRemoved = diffData?.total_removed || 0;

  return (
    <div className={clsx("flex flex-col md:border-l border-[#1a1a1a] bg-[#030303] transition-all duration-200 md:mr-1 h-full", collapsed ? "w-[32px]" : "w-full md:w-[280px]")}>
      {/* Header */}
      <div className="flex items-center gap-2 px-3 py-2.5 border-b border-[#1a1a1a]">
        {!collapsed && (
          <>
            <svg width="12" height="12" viewBox="0 0 12 12" fill="none" stroke="#888" strokeWidth="1.5" strokeLinecap="round">
              <path d="M6 1v10M6 1L3 4M6 1l3 3" />
              <circle cx="6" cy="11" r="0" /><circle cx="3" cy="6" r="1" /><circle cx="9" cy="8" r="1" />
              <line x1="3" y1="6" x2="6" y2="6" /><line x1="9" y1="8" x2="6" y2="8" />
            </svg>
            <span className="text-[11px] font-bold uppercase tracking-[0.15em] text-[#999]">Changes</span>
            {diffData?.source && (
              <span className={clsx(
                "text-[7px] rounded px-1 py-0.5 uppercase tracking-wider",
                diffData.source === "live" ? "text-[#00ff88]/50 bg-[#00ff88]/8" :
                diffData.source === "stored" ? "text-[#88ccff]/50 bg-[#88ccff]/8" :
                "text-[#999] bg-white/[0.03]"
              )}>
                {diffData.source === "live" ? "live" : diffData.source === "stored" ? "git" : diffData.source}
              </span>
            )}
            <span className="text-[10px] text-[#777] tabular-nums ml-auto">{totalFiles} files</span>
          </>
        )}
        <button onClick={() => setCollapsed(!collapsed)} className="text-[#777] hover:text-[#ccc] transition-colors p-0.5">
          <svg width="10" height="10" viewBox="0 0 10 10" fill="none" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round">
            {collapsed ? <polyline points="3 2 7 5 3 8" /> : <polyline points="7 2 3 5 7 8" />}
          </svg>
        </button>
      </div>

      {!collapsed && (
        <>
          {/* Stats */}
          {(totalAdded > 0 || totalRemoved > 0) && (
            <div className="flex items-center gap-3 px-3 py-1.5 border-b border-[#1a1a1a]/60 text-[10px] text-[#888]">
              <span>{totalFiles} files changed</span>
              {totalAdded > 0 && <span className="text-[#00ff88]/70">+{totalAdded}</span>}
              {totalRemoved > 0 && <span className="text-[#ff4444]/70">-{totalRemoved}</span>}
            </div>
          )}

          {/* Tabs */}
          <div className="flex border-b border-[#1a1a1a]/60">
            {hasGitDiff && (
              <button onClick={() => setActiveTab("tree")}
                className={clsx("flex-1 py-1.5 text-[10px] font-medium text-center transition-colors",
                  activeTab === "tree" ? "text-[#e8e8e8] border-b border-[#00ff88]" : "text-[#888] hover:text-[#ccc]")}>
                Tree
              </button>
            )}
            {hasGitDiff && (
              <button onClick={() => setActiveTab("files")}
                className={clsx("flex-1 py-1.5 text-[10px] font-medium text-center transition-colors",
                  activeTab === "files" ? "text-[#e8e8e8] border-b border-[#00ff88]" : "text-[#888] hover:text-[#ccc]")}>
                Files
              </button>
            )}
            {hasLive && (
              <button onClick={() => setActiveTab("live")}
                className={clsx("flex-1 py-1.5 text-[10px] font-medium text-center transition-colors",
                  activeTab === "live" ? "text-[#e8e8e8] border-b border-[#00ff88]" : "text-[#888] hover:text-[#ccc]")}>
                Session
              </button>
            )}
            {!hasGitDiff && !hasLive && (
              <div className="flex-1 py-1.5 text-[10px] text-[#777] text-center">
                {diffLoading ? "Loading..." : "No changes"}
              </div>
            )}
          </div>

          {/* Content */}
          <div className="flex-1 overflow-y-auto py-1">
            {diffLoading && !diffData && (
              <div className="flex items-center justify-center py-8">
                <div className="h-4 w-4 rounded-full border-2 border-[#333] border-t-[#00ff88]" style={{ animation: "spin 1s linear infinite" }} />
              </div>
            )}

            {activeTab === "tree" && diffTree && diffTree.children.size > 0 && (
              Array.from(diffTree.children.values())
                .sort((a, b) => a.isDir === b.isDir ? a.name.localeCompare(b.name) : a.isDir ? -1 : 1)
                .map(child => <NodeItem key={child.fullPath} node={child} depth={0} />)
            )}

            {activeTab === "files" && diffData && diffData.files.length > 0 && (
              <FileList files={diffData.files} />
            )}

            {activeTab === "live" && liveTree.children.size > 0 && (
              Array.from(liveTree.children.values())
                .sort((a, b) => a.isDir === b.isDir ? a.name.localeCompare(b.name) : a.isDir ? -1 : 1)
                .map(child => <NodeItem key={child.fullPath} node={child} depth={0} />)
            )}

            {!diffLoading && !hasGitDiff && !hasLive && (
              <div className="text-[10px] text-[#777] px-3 py-6 text-center">
                No file changes detected yet
              </div>
            )}
          </div>
        </>
      )}
    </div>
  );
}
