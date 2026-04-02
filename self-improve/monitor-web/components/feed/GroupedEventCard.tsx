"use client";

import { useState, useMemo, useEffect } from "react";
import { motion } from "framer-motion";
import { clsx } from "clsx";
import type { ToolCall } from "@/lib/types";
import { getToolCategory, TOOL_COLORS, type ToolCategory } from "@/lib/types";
import { getToolIcon } from "@/components/ui/ToolIcons";
import type { GroupedEvent } from "@/lib/groupEvents";
import { extractReadPaths, extractEditSummary, extractBashCommands } from "@/lib/groupEvents";

/* ── Helpers ── */
function fmtTime(ts: string): string {
  try { return new Date(ts).toLocaleTimeString("en-US", { hour12: false, hour: "2-digit", minute: "2-digit", second: "2-digit" }); }
  catch { return ""; }
}
function fmtDuration(ms: number): string {
  if (ms < 1000) return `${ms}ms`;
  if (ms < 60000) return `${(ms / 1000).toFixed(1)}s`;
  return `${(ms / 60000).toFixed(1)}m`;
}
function shortPath(p: string): string {
  const parts = p.split("/");
  return parts.length <= 2 ? p : parts.slice(-2).join("/");
}

/* ── Chevron ── */
function Chevron({ open, size = 10 }: { open: boolean; size?: number }) {
  return (
    <svg width={size} height={size} viewBox="0 0 10 10" fill="none" stroke="#888" strokeWidth="1.5" strokeLinecap="round"
      className={clsx("shrink-0 transition-transform duration-150", open && "rotate-90")}>
      <polyline points="3 2 7 5 3 8" />
    </svg>
  );
}

/* ── Styled output renderers ── */

function TerminalOutput({ stdout, stderr }: { stdout: string; stderr: string }) {
  const text = stdout || stderr;
  if (!text) return <div className="text-[9px] text-[#777] italic py-1">no output</div>;
  const lines = text.split("\n");
  return (
    <div className="font-mono text-[10px] leading-relaxed max-h-[300px] overflow-y-auto">
      {lines.map((line, i) => (
        <div key={i} className={clsx(
          "px-0.5",
          stderr && !stdout ? "text-[#ff6666]" : "text-[#999]",
          line.startsWith("error") || line.startsWith("Error") || line.startsWith("ERR") ? "text-[#ff6666]" : "",
          line.startsWith("warning") || line.startsWith("Warning") || line.startsWith("WARN") ? "text-[#ffaa00]" : "",
        )}>
          {line || "\u00A0"}
        </div>
      ))}
    </div>
  );
}

function FileContentPreview({ content, totalLines, filePath }: { content: string; totalLines: number; filePath: string }) {
  const ext = filePath.split(".").pop()?.toLowerCase() || "";
  const lines = content.split("\n").slice(0, 30);
  return (
    <div className="rounded border border-[#1a1a1a] overflow-hidden bg-black/30">
      <div className="flex items-center gap-2 px-3 py-1.5 bg-[#0a0a0a] border-b border-[#1a1a1a]">
        <div className="flex gap-1">
          <span className="h-2 w-2 rounded-full bg-[#ff4444]/30" />
          <span className="h-2 w-2 rounded-full bg-[#ffaa00]/30" />
          <span className="h-2 w-2 rounded-full bg-[#00ff88]/30" />
        </div>
        <span className="text-[9px] text-[#666] flex-1 truncate">{shortPath(filePath)}</span>
        <span className="text-[9px] text-[#777] tabular-nums">{totalLines} lines</span>
        {ext && <span className="text-[9px] text-[#888] bg-white/[0.04] rounded px-1 py-0.5 uppercase">{ext}</span>}
      </div>
      <div className="font-mono text-[10px] leading-relaxed max-h-[250px] overflow-y-auto">
        {lines.map((line, i) => (
          <div key={i} className="flex">
            <span className="w-8 shrink-0 text-right pr-2 text-[#888] select-none">{i + 1}</span>
            <span className="text-[#888] whitespace-pre-wrap break-all">{line || "\u00A0"}</span>
          </div>
        ))}
        {totalLines > 30 && (
          <div className="px-2 py-1 text-[9px] text-[#777] text-center">
            … {totalLines - 30} more lines
          </div>
        )}
      </div>
    </div>
  );
}

function DiffBlock({ patch }: { patch: Array<Record<string, unknown>> }) {
  return (
    <div className="rounded border border-[#1a1a1a] overflow-hidden bg-black/30 max-h-[400px] overflow-y-auto font-mono text-[10px]">
      {patch.map((hunk, hi) => {
        const lines = (hunk.lines as string[]) || [];
        return (
          <div key={hi}>
            <div className="text-[9px] text-[#888] px-3 py-1 bg-[#0a0a0a] border-b border-[#1a1a1a] font-semibold">
              @@ -{String(hunk.oldStart)},{String(hunk.oldLines)} +{String(hunk.newStart)},{String(hunk.newLines)} @@
            </div>
            {lines.map((line, li) => {
              const isAdd = line.startsWith("+") && !line.startsWith("+++");
              const isDel = line.startsWith("-") && !line.startsWith("---");
              return (
                <div key={li} className={clsx(
                  "flex",
                  isAdd && "bg-[#00ff88]/[0.04]",
                  isDel && "bg-[#ff4444]/[0.04]",
                )}>
                  <span className={clsx(
                    "w-5 shrink-0 text-center select-none text-[9px]",
                    isAdd ? "text-[#00ff88]/40" : isDel ? "text-[#ff4444]/40" : "text-[#888]"
                  )}>
                    {isAdd ? "+" : isDel ? "−" : " "}
                  </span>
                  <span className={clsx(
                    "whitespace-pre-wrap break-all flex-1 px-1",
                    isAdd ? "text-[#88ffbb]" : isDel ? "text-[#ff8888]" : "text-[#888]"
                  )}>
                    {line.slice(1)}
                  </span>
                </div>
              );
            })}
          </div>
        );
      })}
    </div>
  );
}

function GrepResults({ tool }: { tool: ToolCall }) {
  const input = tool.input_data || {};
  const output = tool.output_data || {};
  const pattern = String(input.pattern || "");
  const content = String((output as Record<string, unknown>).content || (output as Record<string, unknown>).output || JSON.stringify(output));
  const lines = content.split("\n").filter(Boolean).slice(0, 30);

  return (
    <div className="rounded border border-[#1a1a1a] overflow-hidden bg-black/30">
      <div className="flex items-center gap-2 px-3 py-1.5 bg-[#0a0a0a] border-b border-[#1a1a1a]">
        <span className="text-[9px] text-[#88ffcc]">/{pattern}/</span>
        <span className="text-[9px] text-[#777]">{lines.length} matches</span>
      </div>
      <div className="font-mono text-[10px] leading-relaxed max-h-[200px] overflow-y-auto px-3 py-1.5">
        {lines.map((line, i) => (
          <div key={i} className="text-[#888]">{line}</div>
        ))}
      </div>
    </div>
  );
}

function GlobResults({ tool }: { tool: ToolCall }) {
  const output = tool.output_data;
  if (!output) return null;
  const raw = JSON.stringify(output);
  const paths = raw.match(/[^\s"[\],{}]+\.\w+/g) || [];
  if (paths.length === 0) return <pre className="text-[10px] text-[#888] whitespace-pre-wrap">{raw.slice(0, 500)}</pre>;

  return (
    <div className="space-y-0.5 max-h-[200px] overflow-y-auto">
      {paths.slice(0, 20).map((p, i) => (
        <div key={i} className="flex items-center gap-1.5 text-[10px]">
          <svg width="10" height="10" viewBox="0 0 10 10" fill="none" stroke="#ff88aa" strokeWidth="1" opacity="0.4">
            <path d="M2.5 1h4l2 2v5.5a.5.5 0 01-.5.5h-5a.5.5 0 01-.5-.5v-7a.5.5 0 01.5-.5z" />
          </svg>
          <span className="text-[#888]">{p}</span>
        </div>
      ))}
      {paths.length > 20 && <div className="text-[9px] text-[#777]">+{paths.length - 20} more</div>}
    </div>
  );
}

function TodoDisplay({ todos }: { todos: Array<{ status: string; content: string }> }) {
  return (
    <div className="space-y-1.5">
      {todos.map((t, i) => (
        <div key={i} className="flex items-start gap-2 text-[10px]">
          <span className={clsx("mt-0.5 shrink-0",
            t.status === "completed" ? "text-[#00ff88]" : t.status === "in_progress" ? "text-[#ffaa00]" : "text-[#777]"
          )}>
            {t.status === "completed" ? (
              <svg width="11" height="11" viewBox="0 0 11 11" fill="none" stroke="currentColor" strokeWidth="1.5"><polyline points="2.5 5.5 4.5 7.5 8.5 3.5" /></svg>
            ) : t.status === "in_progress" ? (
              <svg width="11" height="11" viewBox="0 0 11 11" fill="none" stroke="currentColor" strokeWidth="1.5" className="animate-pulse"><circle cx="5.5" cy="5.5" r="3.5" /></svg>
            ) : (
              <svg width="11" height="11" viewBox="0 0 11 11" fill="none" stroke="currentColor" strokeWidth="1.5"><rect x="2" y="2" width="7" height="7" rx="1" /></svg>
            )}
          </span>
          <span className={clsx(
            t.status === "completed" && "text-[#666] line-through",
            t.status === "in_progress" && "text-[#ddd]",
            t.status === "pending" && "text-[#888]"
          )}>
            {t.content}
          </span>
        </div>
      ))}
    </div>
  );
}

/* ── Styled output for SingleTool expanded ── */
function StyledToolOutput({ tool }: { tool: ToolCall }) {
  const cat = getToolCategory(tool.tool_name);
  const input = tool.input_data || {};
  const output = tool.output_data || {};

  // Bash: terminal output
  if (cat === "bash" && tool.output_data) {
    return (
      <div className="space-y-2">
        {!!input.command && (
          <div className="flex items-center gap-1.5 font-mono text-[10px]">
            <span className="text-[#00ff88]/60">$</span>
            <span className="text-[#ccc]">{String(input.command).slice(0, 200)}</span>
          </div>
        )}
        <div className="rounded border border-[#1a1a1a] bg-black/30 p-2.5">
          <TerminalOutput stdout={String(output.stdout || "")} stderr={String(output.stderr || "")} />
        </div>
      </div>
    );
  }

  // Read: file content preview
  if (cat === "read" && tool.output_data) {
    const fileObj = (output.file as Record<string, unknown>) || {};
    const content = String(fileObj.content || "");
    const totalLines = Number(fileObj.totalLines || 0);
    const filePath = String(fileObj.filePath || input.file_path || "");
    if (content) {
      return <FileContentPreview content={content} totalLines={totalLines} filePath={filePath} />;
    }
  }

  // Edit: diff view
  if ((cat === "edit" || cat === "write") && tool.output_data?.structuredPatch) {
    return <DiffBlock patch={output.structuredPatch as Array<Record<string, unknown>>} />;
  }

  // Grep: search results
  if (cat === "grep" && tool.output_data) {
    return <GrepResults tool={tool} />;
  }

  // Glob: file list
  if (cat === "glob" && tool.output_data) {
    return <GlobResults tool={tool} />;
  }

  // Todo: task list
  if (cat === "todo" && input.todos) {
    return <TodoDisplay todos={input.todos as Array<{ status: string; content: string }>} />;
  }

  // WebSearch/WebFetch: render as text if possible
  if ((cat === "web_search" || cat === "web_fetch") && tool.output_data) {
    const text = String((output as Record<string, unknown>).content || (output as Record<string, unknown>).text || "");
    if (text && text !== "undefined") {
      return (
        <div className="rounded border border-[#1a1a1a] bg-black/30 p-3 max-h-[300px] overflow-y-auto text-[10px] text-[#888] whitespace-pre-wrap break-words leading-relaxed">
          {text.slice(0, 3000)}
        </div>
      );
    }
  }

  // Fallback: pretty JSON
  if (tool.output_data) {
    return (
      <pre className="text-[10px] text-[#666] bg-black/20 rounded border border-[#1a1a1a] p-2.5 whitespace-pre-wrap break-all max-h-[300px] overflow-y-auto font-mono leading-relaxed">
        {JSON.stringify(tool.output_data, null, 2)}
      </pre>
    );
  }

  return null;
}

/* ═══════════════════════════════════════════════
   CARD COMPONENTS
   ═══════════════════════════════════════════════ */

/* ── LLM Message ── */
function LLMMessageCard({ role, text, thinking, ts, isLast }: { role: string; text: string; thinking: string; ts: string; isLast: boolean }) {
  const [showThinking, setShowThinking] = useState(false);
  const [collapsed, setCollapsed] = useState(false);
  const isCeo = role === "ceo";
  const isLong = text.length > 3000;

  return (
    <motion.div initial={{ opacity: 0, y: 6 }} animate={{ opacity: 1, y: 0 }} transition={{ duration: 0.2 }}
      className={clsx("rounded-lg p-4", isCeo ? "bg-[#ff8844]/[0.04] border border-[#ff8844]/10" : "bg-white/[0.02] border border-white/[0.04]")}>
      <div className="flex items-center gap-2 mb-2.5">
        <div className={clsx("flex items-center justify-center h-6 w-6 rounded-md", isCeo ? "bg-[#ff8844]/10" : "bg-[#00ff88]/8")}>
          {isCeo ? (
            <svg width="12" height="12" viewBox="0 0 12 12" fill="none" stroke="#ff8844" strokeWidth="1.5"><path d="M2 9l2-4 2 2.5 2-3.5 2 5" /><rect x="1" y="9" width="10" height="1.5" rx="0.5" /></svg>
          ) : (
            <svg width="12" height="12" viewBox="0 0 12 12" fill="none" stroke="#00ff88" strokeWidth="1.5"><path d="M6 1l1 3h3l-2.5 2 1 3L6 7.5 3.5 9l1-3L2 4h3L6 1z" /></svg>
          )}
        </div>
        <span className={clsx("text-[11px] font-semibold", isCeo ? "text-[#ff8844]" : "text-[#ccc]")}>
          {isCeo ? "CEO" : "Worker Agent"}
        </span>
        <span className="text-[9px] text-[#777] tabular-nums">{fmtTime(ts)}</span>
        {thinking && (
          <button onClick={() => setShowThinking(!showThinking)}
            className="ml-auto text-[9px] text-[#888] hover:text-[#888] transition-colors flex items-center gap-1">
            <svg width="10" height="10" viewBox="0 0 10 10" fill="none" stroke="currentColor" strokeWidth="1.5"><circle cx="5" cy="5" r="3.5" /><circle cx="5" cy="5" r="1" /></svg>
            {showThinking ? "hide reasoning" : "show reasoning"}
          </button>
        )}
      </div>

      {showThinking && thinking && (
        <motion.div initial={{ height: 0, opacity: 0 }} animate={{ height: "auto", opacity: 1 }}
          className="mb-3 px-3 py-2 bg-black/20 rounded border border-white/[0.03] overflow-hidden">
          <div className="text-[9px] text-[#888] uppercase tracking-wider font-semibold mb-1">Reasoning</div>
          <div className="text-[10px] text-[#666] italic leading-relaxed whitespace-pre-wrap break-words max-h-[300px] overflow-y-auto">{thinking}</div>
        </motion.div>
      )}

      {text && (
        <div className="relative">
          {isLong && (
            <button onClick={() => setCollapsed(!collapsed)} className="absolute top-0 right-0 text-[9px] text-[#888] hover:text-[#888] transition-colors">
              [{collapsed ? "expand" : "collapse"}]
            </button>
          )}
          <div className={clsx("text-[11px] leading-[1.7] whitespace-pre-wrap break-words", isCeo ? "text-[#cc9966]" : "text-[#bbb]", collapsed && "max-h-[100px] overflow-hidden")}>
            {collapsed ? text.slice(0, 500) + "…" : text}
          </div>
          {collapsed && <div className="absolute bottom-0 left-0 right-0 h-8 bg-gradient-to-t from-[#050505] to-transparent" />}
          {/* Only show blinking cursor on the last message */}
          {isLast && (
            <span className={clsx("inline-block w-[5px] h-[13px] ml-0.5 rounded-[1px]", isCeo ? "bg-[#ff8844]/30" : "bg-[#00ff88]/25")}
              style={{ animation: "blink 1s step-end infinite" }} />
          )}
        </div>
      )}
    </motion.div>
  );
}

/* ── Read Group ── */
function ReadGroupCard({ tools, ts, totalDuration, label }: { tools: ToolCall[]; ts: string; totalDuration: number; label: string }) {
  const [expanded, setExpanded] = useState(false);
  const [previewIdx, setPreviewIdx] = useState<number | null>(null);
  const paths = useMemo(() => extractReadPaths(tools), [tools]);

  return (
    <motion.div initial={{ opacity: 0, y: 4 }} animate={{ opacity: 1, y: 0 }}
      className="rounded-lg border border-[#88ccff]/8 bg-[#88ccff]/[0.02] overflow-hidden">
      <button onClick={() => setExpanded(!expanded)}
        className="w-full flex items-center gap-3 px-4 py-3 hover:bg-white/[0.02] transition-colors text-left">
        <div className="flex items-center justify-center h-8 w-8 rounded-md bg-[#88ccff]/8 shrink-0">{getToolIcon("read", "#88ccff")}</div>
        <div className="flex-1 min-w-0">
          <div className="text-[11px] font-medium text-[#88ccff]">{label}</div>
          <div className="text-[9px] text-[#888] mt-0.5 truncate">
            {paths.slice(0, 3).map(p => shortPath(p)).join(", ")}{paths.length > 3 && ` +${paths.length - 3} more`}
          </div>
        </div>
        <span className="text-[9px] text-[#777] tabular-nums shrink-0">{fmtTime(ts)}</span>
        {totalDuration > 0 && <span className="text-[9px] text-[#888] tabular-nums shrink-0">{fmtDuration(totalDuration)}</span>}
        <Chevron open={expanded} />
      </button>

      {expanded && (
        <motion.div initial={{ height: 0 }} animate={{ height: "auto" }} className="border-t border-white/[0.04] overflow-hidden">
          <div className="px-4 py-2 space-y-1 max-h-[500px] overflow-y-auto">
            {paths.map((p, i) => {
              const fileObj = (tools[i]?.output_data as Record<string, unknown>)?.file as Record<string, unknown> | undefined;
              const totalLines = Number(fileObj?.totalLines || 0);
              return (
                <div key={i}>
                  <button onClick={() => setPreviewIdx(previewIdx === i ? null : i)}
                    className="w-full flex items-center gap-2 text-[10px] py-1 hover:bg-white/[0.02] rounded px-1 transition-colors text-left">
                    <svg width="10" height="10" viewBox="0 0 10 10" fill="none" stroke="#88ccff" strokeWidth="1" opacity="0.4">
                      <path d="M2.5 1h4l2 2v5.5a.5.5 0 01-.5.5h-5a.5.5 0 01-.5-.5v-7a.5.5 0 01.5-.5z" />
                    </svg>
                    <span className="text-[#888] truncate flex-1">{p}</span>
                    {totalLines > 0 && <span className="text-[9px] text-[#888] shrink-0 tabular-nums">{totalLines} lines</span>}
                    <Chevron open={previewIdx === i} size={8} />
                  </button>
                  {previewIdx === i && !!(fileObj?.content) && (
                    <div className="ml-4 mt-1 mb-2">
                      <FileContentPreview content={String(fileObj.content)} totalLines={totalLines} filePath={p} />
                    </div>
                  )}
                </div>
              );
            })}
          </div>
        </motion.div>
      )}
    </motion.div>
  );
}

/* ── Edit Group ── */
function EditGroupCard({ tools, ts, totalDuration }: { tools: ToolCall[]; ts: string; totalDuration: number }) {
  const [expanded, setExpanded] = useState(false);
  const [expandedFile, setExpandedFile] = useState<number | null>(null);
  const edits = useMemo(() => extractEditSummary(tools), [tools]);
  const totalAdded = edits.reduce((s, e) => s + e.added, 0);
  const totalRemoved = edits.reduce((s, e) => s + e.removed, 0);
  const uniqueFiles = new Set(edits.map(e => e.path)).size;

  return (
    <motion.div initial={{ opacity: 0, y: 4 }} animate={{ opacity: 1, y: 0 }}
      className="rounded-lg border border-[#ffcc44]/8 bg-[#ffcc44]/[0.02] overflow-hidden">
      <button onClick={() => setExpanded(!expanded)}
        className="w-full flex items-center gap-3 px-4 py-3 hover:bg-white/[0.02] transition-colors text-left">
        <div className="flex items-center justify-center h-8 w-8 rounded-md bg-[#ffcc44]/8 shrink-0">{getToolIcon("edit", "#ffcc44")}</div>
        <div className="flex-1 min-w-0">
          <div className="text-[11px] font-medium text-[#ffcc44]">Edited {uniqueFiles} file{uniqueFiles !== 1 ? "s" : ""} ({edits.length} changes)</div>
          <div className="flex items-center gap-2 mt-0.5">
            {totalAdded > 0 && <span className="text-[9px] text-[#00ff88]/60 tabular-nums">+{totalAdded}</span>}
            {totalRemoved > 0 && <span className="text-[9px] text-[#ff4444]/60 tabular-nums">-{totalRemoved}</span>}
          </div>
        </div>
        <span className="text-[9px] text-[#777] tabular-nums shrink-0">{fmtTime(ts)}</span>
        {totalDuration > 0 && <span className="text-[9px] text-[#888] tabular-nums shrink-0">{fmtDuration(totalDuration)}</span>}
        <Chevron open={expanded} />
      </button>
      {expanded && (
        <motion.div initial={{ height: 0 }} animate={{ height: "auto" }} className="border-t border-white/[0.04] overflow-hidden">
          <div className="divide-y divide-white/[0.03]">
            {edits.map((edit, i) => (
              <div key={i}>
                <button onClick={() => setExpandedFile(expandedFile === i ? null : i)}
                  className="w-full flex items-center gap-2 px-4 py-2 text-[10px] hover:bg-white/[0.02] transition-colors text-left">
                  <svg width="10" height="10" viewBox="0 0 10 10" fill="none" stroke="#ffcc44" strokeWidth="1" opacity="0.5"><path d="M6.5 1L8 2.5 3 7.5H1.5V6L6.5 1z" /></svg>
                  <span className="text-[#999] truncate flex-1">{edit.path}</span>
                  {edit.added > 0 && <span className="text-[#00ff88]/50 tabular-nums shrink-0">+{edit.added}</span>}
                  {edit.removed > 0 && <span className="text-[#ff4444]/50 tabular-nums shrink-0">-{edit.removed}</span>}
                  <Chevron open={expandedFile === i} size={8} />
                </button>
                {expandedFile === i && !!(tools[i]?.output_data?.structuredPatch) && (
                  <div className="px-4 pb-3">
                    <DiffBlock patch={tools[i].output_data!.structuredPatch as Array<Record<string, unknown>>} />
                  </div>
                )}
              </div>
            ))}
          </div>
        </motion.div>
      )}
    </motion.div>
  );
}

/* ── Bash Group ── */
function BashGroupCard({ tools, ts, totalDuration }: { tools: ToolCall[]; ts: string; totalDuration: number }) {
  const [expanded, setExpanded] = useState(false);
  const commands = useMemo(() => extractBashCommands(tools), [tools]);

  return (
    <motion.div initial={{ opacity: 0, y: 4 }} animate={{ opacity: 1, y: 0 }}
      className="rounded-lg border border-[#00ff88]/8 bg-[#00ff88]/[0.02] overflow-hidden">
      <button onClick={() => setExpanded(!expanded)}
        className="w-full flex items-center gap-3 px-4 py-3 hover:bg-white/[0.02] transition-colors text-left">
        <div className="flex items-center justify-center h-8 w-8 rounded-md bg-[#00ff88]/8 shrink-0">{getToolIcon("bash", "#00ff88")}</div>
        <div className="flex-1 min-w-0">
          <div className="text-[11px] font-medium text-[#00ff88]">Terminal · {commands.length} command{commands.length !== 1 ? "s" : ""}</div>
          <div className="text-[9px] text-[#888] mt-0.5 truncate">{commands[0]?.cmd}{commands.length > 1 ? ` + ${commands.length - 1} more` : ""}</div>
        </div>
        <span className="text-[9px] text-[#777] tabular-nums shrink-0">{fmtTime(ts)}</span>
        {totalDuration > 0 && <span className="text-[9px] text-[#888] tabular-nums shrink-0">{fmtDuration(totalDuration)}</span>}
        <Chevron open={expanded} />
      </button>
      {expanded && (
        <motion.div initial={{ height: 0 }} animate={{ height: "auto" }} className="border-t border-white/[0.04] overflow-hidden">
          <div className="rounded-b-lg overflow-hidden">
            {/* Terminal chrome */}
            <div className="flex items-center gap-1.5 px-3 py-1.5 bg-[#0a0a0a] border-b border-[#1a1a1a]">
              <span className="h-2 w-2 rounded-full bg-[#ff4444]/30" />
              <span className="h-2 w-2 rounded-full bg-[#ffaa00]/30" />
              <span className="h-2 w-2 rounded-full bg-[#00ff88]/30" />
              <span className="text-[9px] text-[#777] ml-2">bash</span>
            </div>
            <div className="bg-black/40 p-3 space-y-3 max-h-[500px] overflow-y-auto font-mono text-[10px]">
              {commands.map((cmd, i) => (
                <div key={i}>
                  <div className="flex items-center gap-1.5">
                    <span className="text-[#00ff88]/60">$</span>
                    <span className="text-[#ccc] flex-1">{cmd.cmd}</span>
                    {cmd.duration > 0 && <span className="text-[9px] text-[#777]">{fmtDuration(cmd.duration)}</span>}
                  </div>
                  {cmd.output && (
                    <div className="mt-1 ml-3.5 border-l border-white/[0.04] pl-2.5">
                      <TerminalOutput stdout={cmd.exitOk ? cmd.output : ""} stderr={cmd.exitOk ? "" : cmd.output} />
                    </div>
                  )}
                </div>
              ))}
            </div>
          </div>
        </motion.div>
      )}
    </motion.div>
  );
}

/* ── Agent Run ── */
// Idle threshold for stuck agent warning display
const IDLE_WARN_MS = 60_000;    // 1 minute — show warning (backend handles kill at 10 min)

function AgentRunCard({ tool, childTools, finalText, ts }: { tool: ToolCall; childTools: ToolCall[]; finalText: string; ts: string }) {
  const [expanded, setExpanded] = useState(false);
  const [showPrompt, setShowPrompt] = useState(false);
  const [showFinalText, setShowFinalText] = useState(false);
  const [now, setNow] = useState(Date.now());
  const input = tool.input_data || {};
  const description = (input.description as string) || "Sub-agent task";
  const prompt = (input.prompt as string) || "";
  const subType = (input.subagent_type as string) || "general";
  const isPending = tool.phase === "pre" && !tool.output_data;

  // Last activity timestamp: last child tool, or the agent call itself
  const lastActivityTs = childTools.length > 0
    ? new Date(childTools[childTools.length - 1].ts).getTime()
    : new Date(ts).getTime();
  const idleMs = isPending ? now - lastActivityTs : 0;
  const isIdle = idleMs > IDLE_WARN_MS;
  const idleSec = Math.floor(idleMs / 1000);

  // Detect "finalizing" — last tool completed > 3s ago but agent not done yet (and not stuck)
  const isFinalizing = isPending && childTools.length > 0 && idleMs > 3000 && !isIdle;

  // Tick every second when pending (for idle timer)
  useEffect(() => {
    if (!isPending) return;
    const id = setInterval(() => setNow(Date.now()), 1000);
    return () => clearInterval(id);
  }, [isPending]);

  // Summarize child tools by category
  const childSummary = useMemo(() => {
    const counts = new Map<ToolCategory, number>();
    for (const ct of childTools) {
      const cat = getToolCategory(ct.tool_name);
      counts.set(cat, (counts.get(cat) || 0) + 1);
    }
    return Array.from(counts.entries())
      .sort((a, b) => b[1] - a[1])
      .map(([cat, count]) => ({ cat, count }));
  }, [childTools]);

  const lastChild = childTools.length > 0 ? childTools[childTools.length - 1] : null;
  const totalChildDuration = childTools.reduce((sum, t) => sum + (t.duration_ms || 0), 0);

  return (
    <motion.div initial={{ opacity: 0, y: 4 }} animate={{ opacity: 1, y: 0 }}
      className={clsx(
        "rounded-lg border overflow-hidden relative",
        isIdle
          ? "border-[#ff4444]/30 bg-gradient-to-r from-[#ff4444]/[0.05] via-[#ff4444]/[0.02] to-[#ff4444]/[0.05]"
          : isPending
            ? "border-[#ff8844]/25 bg-gradient-to-r from-[#ff8844]/[0.04] via-[#ff8844]/[0.02] to-[#ff8844]/[0.04]"
            : "border-[#ff8844]/10 bg-[#ff8844]/[0.02]"
      )}>
      {/* Animated top border accent when running */}
      {isPending && (
        <div className="absolute top-0 left-0 right-0 h-[2px] overflow-hidden">
          <div
            className="h-full w-[200%]"
            style={{
              background: isIdle
                ? "linear-gradient(90deg, transparent 0%, #ff4444 25%, #ff6644 50%, #ff4444 75%, transparent 100%)"
                : "linear-gradient(90deg, transparent 0%, #ff8844 25%, #ffaa00 50%, #ff8844 75%, transparent 100%)",
              animation: isIdle ? "agent-shimmer 1s linear infinite" : "agent-shimmer 2s linear infinite",
            }}
          />
        </div>
      )}
      <style>{`@keyframes agent-shimmer { 0% { transform: translateX(-50%); } 100% { transform: translateX(0); } }`}</style>

      {/* Header */}
      <button onClick={() => setExpanded(!expanded)}
        className="w-full flex items-center gap-3 px-4 py-3 hover:bg-white/[0.02] transition-colors text-left">
        <div className="relative flex items-center justify-center h-8 w-8 rounded-md shrink-0"
          style={isPending ? { background: "rgba(255, 136, 68, 0.12)", boxShadow: "0 0 12px rgba(255, 136, 68, 0.15)" } : { background: "rgba(255, 136, 68, 0.08)" }}>
          {getToolIcon("agent", isPending ? "#ffaa44" : "#ff8844")}
          {isPending && (
            <>
              <span className="absolute inset-0 rounded-md border border-[#ff8844]/20" style={{ animation: "agent-ring 2s ease-out infinite" }} />
              <span className="absolute -top-0.5 -right-0.5 h-2.5 w-2.5 rounded-full bg-[#ffaa00]" style={{ boxShadow: "0 0 6px rgba(255, 170, 0, 0.6)" }}>
                <span className="absolute inset-0 rounded-full bg-[#ffaa00] animate-ping opacity-40" />
              </span>
            </>
          )}
        </div>
        <style>{`@keyframes agent-ring { 0% { opacity: 0.6; transform: scale(1); } 100% { opacity: 0; transform: scale(1.4); } }`}</style>
        <div className="flex-1 min-w-0">
          <div className="flex items-center gap-2">
            <span className={clsx("text-[11px] font-medium", isPending ? "text-[#ffaa44]" : "text-[#ff8844]")}>{description}</span>
            <span className="text-[9px] text-[#ff8844]/40 bg-[#ff8844]/8 rounded px-1 py-0.5 uppercase tracking-wider">{subType}</span>
            {childTools.length > 0 && (
              <span className="text-[9px] text-[#888] tabular-nums">{childTools.length} tools</span>
            )}
          </div>
          {/* Live status line — shows last tool or category summary */}
          {!expanded && childTools.length > 0 && (
            <div className="flex items-center gap-2 mt-0.5">
              {isPending && !isFinalizing && lastChild && (
                <motion.span
                  key={lastChild.id}
                  initial={{ opacity: 0, x: -4 }}
                  animate={{ opacity: 1, x: 0 }}
                  className="flex items-center gap-1 text-[9px] text-[#ccc]"
                >
                  <span className="opacity-60 shrink-0">{getToolIcon(getToolCategory(lastChild.tool_name), "#ffaa44")}</span>
                  <span className="truncate max-w-[220px]">
                    {lastChild.tool_name}
                    {lastChild.input_data?.file_path ? <span className="text-[#888] ml-1">{shortPath(String(lastChild.input_data.file_path))}</span> : null}
                    {lastChild.input_data?.command ? <span className="text-[#888] ml-1">{String(lastChild.input_data.command).slice(0, 40)}</span> : null}
                  </span>
                </motion.span>
              )}
              {isFinalizing && (
                <motion.span
                  initial={{ opacity: 0 }}
                  animate={{ opacity: 1 }}
                  className="flex items-center gap-1.5 text-[9px] text-[#cc88ff]"
                >
                  <svg width="10" height="10" viewBox="0 0 10 10" fill="none" className="animate-spin">
                    <circle cx="5" cy="5" r="4" stroke="#cc88ff" strokeWidth="1" strokeDasharray="12 8" />
                  </svg>
                  writing response...
                </motion.span>
              )}
              {!isPending && (
                <span className="flex items-center gap-1.5 text-[9px] text-[#777]">
                  {childSummary.slice(0, 4).map(({ cat, count }) => (
                    <span key={cat} className="flex items-center gap-0.5">
                      <span className="opacity-40">{getToolIcon(cat, "#888")}</span>
                      <span className="tabular-nums">{count}</span>
                    </span>
                  ))}
                </span>
              )}
            </div>
          )}
          {!expanded && childTools.length === 0 && prompt && (
            <div className="text-[9px] text-[#888] mt-0.5 truncate">{prompt.slice(0, 100)}</div>
          )}
        </div>
        <div className="flex items-center gap-2 shrink-0">
          <span className="text-[9px] text-[#777] tabular-nums">{fmtTime(ts)}</span>
          {!!tool.duration_ms && <span className="text-[9px] text-[#888] tabular-nums">{fmtDuration(tool.duration_ms)}</span>}
          {isPending && !isIdle && (
            <span className={clsx("flex items-center gap-1.5 text-[9px] font-semibold", isFinalizing ? "text-[#cc88ff]" : "text-[#ffaa00]")}>
              <span className="relative flex h-1.5 w-1.5">
                <span className={clsx("absolute inline-flex h-full w-full rounded-full animate-ping opacity-50", isFinalizing ? "bg-[#cc88ff]" : "bg-[#ffaa00]")} />
                <span className={clsx("relative inline-flex h-1.5 w-1.5 rounded-full", isFinalizing ? "bg-[#cc88ff]" : "bg-[#ffaa00]")} style={{ boxShadow: isFinalizing ? "0 0 4px rgba(204, 136, 255, 0.5)" : "0 0 4px rgba(255, 170, 0, 0.5)" }} />
              </span>
              {isFinalizing ? "finalizing" : "running"}
            </span>
          )}
          {isIdle && (
            <span className="flex items-center gap-1.5 text-[9px] font-semibold text-[#ff4444]">
              <span className="relative flex h-1.5 w-1.5">
                <span className="absolute inline-flex h-full w-full rounded-full bg-[#ff4444] animate-ping opacity-50" />
                <span className="relative inline-flex h-1.5 w-1.5 rounded-full bg-[#ff4444]" style={{ boxShadow: "0 0 4px rgba(255, 68, 68, 0.5)" }} />
              </span>
              stuck
            </span>
          )}
          <Chevron open={expanded} />
        </div>
      </button>

      {/* Stuck agent warning (backend handles kill at 10 min idle) */}
      {isIdle && (
        <div className="border-t border-[#ff4444]/20 bg-[#ff4444]/[0.06] px-4 py-2">
          <div className="flex items-center gap-2.5">
            <svg width="12" height="12" viewBox="0 0 12 12" fill="none" className="shrink-0">
              <path d="M6 1L11 10H1L6 1Z" stroke="#ff4444" strokeWidth="1" fill="none" />
              <line x1="6" y1="4.5" x2="6" y2="7" stroke="#ff4444" strokeWidth="1" strokeLinecap="round" />
              <circle cx="6" cy="8.5" r="0.5" fill="#ff4444" />
            </svg>
            <span className="text-[10px] text-[#ff4444]">
              Agent idle for <span className="font-semibold tabular-nums">{idleSec >= 60 ? `${Math.floor(idleSec / 60)}m ${idleSec % 60}s` : `${idleSec}s`}</span>
              {" "}— auto-recovery at 10m
            </span>
          </div>
        </div>
      )}

      {/* Expanded: child tools + prompt/result */}
      {expanded && (
        <motion.div initial={{ height: 0 }} animate={{ height: "auto" }} className="border-t border-white/[0.04] overflow-hidden">
          {/* Category summary bar */}
          {childTools.length > 0 && (
            <div className="flex items-center gap-3 px-4 py-2 border-b border-white/[0.03] bg-black/10">
              <span className="text-[9px] text-[#888] uppercase tracking-wider">{childTools.length} tool calls</span>
              {totalChildDuration > 0 && <span className="text-[9px] text-[#666] tabular-nums">{fmtDuration(totalChildDuration)}</span>}
              <div className="flex items-center gap-2 ml-auto">
                {childSummary.map(({ cat, count }) => (
                  <span key={cat} className="flex items-center gap-1 text-[9px] text-[#777]">
                    <span className="opacity-50">{getToolIcon(cat, "#888")}</span>
                    <span className="tabular-nums">{count}</span>
                  </span>
                ))}
              </div>
            </div>
          )}

          {/* Child tool list */}
          {childTools.length > 0 && (
            <div className="max-h-[400px] overflow-y-auto">
              {childTools.map((ct, idx) => {
                const cat = getToolCategory(ct.tool_name);
                const colors = TOOL_COLORS[cat];
                const inp = ct.input_data || {};
                const fp = (inp.file_path as string) || "";
                const cmd = (inp.command as string) || "";
                const desc = (inp.description as string) || "";
                const detail = fp ? shortPath(fp) : cmd ? cmd.slice(0, 60) : desc ? desc.slice(0, 60) : "";
                return (
                  <div key={idx}
                    className={clsx(
                      "flex items-center gap-2 px-4 py-1.5 text-[10px] transition-colors hover:bg-white/[0.02]",
                      idx < childTools.length - 1 && "border-b border-white/[0.02]"
                    )}
                  >
                    <span className="opacity-50 shrink-0">{getToolIcon(cat, colors?.iconColor || "#888")}</span>
                    <span className={clsx("shrink-0 font-medium", colors?.text || "text-[#888]")}>{ct.tool_name}</span>
                    {detail && <span className="text-[#666] truncate flex-1 min-w-0">{detail}</span>}
                    {!detail && <span className="flex-1" />}
                    {!!ct.duration_ms && <span className="text-[9px] text-[#666] tabular-nums shrink-0">{fmtDuration(ct.duration_ms)}</span>}
                  </div>
                );
              })}
            </div>
          )}

          {/* Prompt toggle */}
          {prompt && (
            <div className="border-t border-white/[0.03]">
              <button onClick={(e) => { e.stopPropagation(); setShowPrompt(!showPrompt); }}
                className="w-full flex items-center gap-2 px-4 py-2 text-[9px] text-[#888] hover:bg-white/[0.02] transition-colors text-left uppercase tracking-wider">
                <Chevron open={showPrompt} size={8} />
                Prompt
              </button>
              {showPrompt && (
                <div className="px-4 pb-3">
                  <div className="text-[10px] text-[#aaa] whitespace-pre-wrap break-words leading-relaxed bg-black/20 rounded-lg p-3 border border-white/[0.03] max-h-[200px] overflow-y-auto">{prompt}</div>
                </div>
              )}
            </div>
          )}

          {/* Agent's final response (from transcript) */}
          {finalText && (
            <div className="border-t border-white/[0.03]">
              <button onClick={(e) => { e.stopPropagation(); setShowFinalText(!showFinalText); }}
                className="w-full flex items-center gap-2 px-4 py-2 text-[9px] text-[#cc88ff]/70 hover:bg-white/[0.02] transition-colors text-left uppercase tracking-wider">
                <Chevron open={showFinalText} size={8} />
                Agent Summary
              </button>
              {showFinalText && (
                <div className="px-4 pb-3">
                  <div className="text-[10px] text-[#bbb] whitespace-pre-wrap break-words leading-relaxed bg-black/20 rounded-lg p-3 border border-[#cc88ff]/10 max-h-[300px] overflow-y-auto">
                    {finalText}
                  </div>
                </div>
              )}
            </div>
          )}

          {/* Finalizing indicator (when tools done but agent still writing) */}
          {isFinalizing && expanded && (
            <div className="border-t border-white/[0.03] px-4 py-3 flex items-center gap-2">
              <svg width="12" height="12" viewBox="0 0 12 12" fill="none" className="animate-spin shrink-0">
                <circle cx="6" cy="6" r="5" stroke="#cc88ff" strokeWidth="1" strokeDasharray="16 10" />
              </svg>
              <span className="text-[10px] text-[#cc88ff]/70">Agent is writing its final response...</span>
            </div>
          )}

          {/* Raw result (when completed) */}
          {tool.output_data && (
            <div className="border-t border-white/[0.03] px-4 py-3">
              <div className="text-[9px] uppercase tracking-[0.15em] text-[#00ff88]/50 mb-1.5">Result</div>
              <div className="text-[10px] text-[#888] whitespace-pre-wrap break-words bg-black/20 rounded-lg p-3 border border-white/[0.03] max-h-[200px] overflow-y-auto leading-relaxed">
                {typeof tool.output_data === "object" && "result" in tool.output_data
                  ? String(tool.output_data.result).slice(0, 2000)
                  : JSON.stringify(tool.output_data, null, 2).slice(0, 2000)}
              </div>
            </div>
          )}
        </motion.div>
      )}
    </motion.div>
  );
}

/* ── Playwright Group ── */
function PlaywrightGroupCard({ tools, ts, totalDuration }: { tools: ToolCall[]; ts: string; totalDuration: number }) {
  const [expanded, setExpanded] = useState(false);
  return (
    <motion.div initial={{ opacity: 0, y: 4 }} animate={{ opacity: 1, y: 0 }}
      className="rounded-lg border border-[#66bbff]/8 bg-[#66bbff]/[0.02] overflow-hidden">
      <button onClick={() => setExpanded(!expanded)}
        className="w-full flex items-center gap-3 px-4 py-3 hover:bg-white/[0.02] transition-colors text-left">
        <div className="flex items-center justify-center h-8 w-8 rounded-md bg-[#66bbff]/8 shrink-0">{getToolIcon("playwright_navigate", "#66bbff")}</div>
        <div className="flex-1 min-w-0">
          <div className="text-[11px] font-medium text-[#66bbff]">Browser · {tools.length} action{tools.length !== 1 ? "s" : ""}</div>
          <div className="text-[9px] text-[#888] mt-0.5 truncate">
            {tools.map(t => getToolCategory(t.tool_name).replace("playwright_", "")).join(" → ")}
          </div>
        </div>
        <span className="text-[9px] text-[#777] tabular-nums shrink-0">{fmtTime(ts)}</span>
        {totalDuration > 0 && <span className="text-[9px] text-[#888] tabular-nums shrink-0">{fmtDuration(totalDuration)}</span>}
        <Chevron open={expanded} />
      </button>
      {expanded && (
        <motion.div initial={{ height: 0 }} animate={{ height: "auto" }} className="border-t border-white/[0.04] overflow-hidden">
          <div className="p-3 space-y-2 max-h-[400px] overflow-y-auto">
            {tools.map((tc, i) => {
              const cat = getToolCategory(tc.tool_name);
              const inp = tc.input_data || {};
              return (
                <div key={i} className="flex items-center gap-2 text-[10px] py-1 px-2 rounded hover:bg-white/[0.02] transition-colors">
                  <span className="opacity-50 shrink-0">{getToolIcon(cat, "#66bbff")}</span>
                  <span className="text-[#888] flex-1">
                    {cat.replace("playwright_", "")}
                    {!!inp.url && <span className="text-[#66bbff]/60 ml-1">{String(inp.url)}</span>}
                    {!!inp.filename && <span className="text-[#66bbff]/60 ml-1">{String(inp.filename)}</span>}
                  </span>
                  {!!tc.duration_ms && <span className="text-[9px] text-[#777] tabular-nums">{fmtDuration(tc.duration_ms)}</span>}
                </div>
              );
            })}
          </div>
        </motion.div>
      )}
    </motion.div>
  );
}

/* ── Single Tool ── */
function SingleToolCard({ tool }: { tool: ToolCall }) {
  const [expanded, setExpanded] = useState(false);
  const cat = getToolCategory(tool.tool_name);
  const colors = TOOL_COLORS[cat];
  const denied = !tool.permitted;
  const isPending = tool.phase === "pre" && !tool.output_data;

  const input = tool.input_data || {};
  let summary = "";
  switch (cat) {
    case "bash": summary = (input.description as string) || (input.command as string)?.slice(0, 100) || ""; break;
    case "read": summary = shortPath((input.file_path as string) || ""); break;
    case "write": case "edit": summary = shortPath((input.file_path as string) || ""); break;
    case "glob": summary = (input.pattern as string) || ""; break;
    case "grep": summary = `/${input.pattern}/ in ${shortPath((input.path as string) || "")}`; break;
    case "todo": { const todos = (input.todos as Array<{status: string}>) || []; summary = `${todos.filter(t => t.status === "completed").length}✓ ${todos.filter(t => t.status === "in_progress").length}◉ ${todos.filter(t => t.status === "pending").length}○`; break; }
    case "skill": summary = (input.skill as string) || ""; break;
    case "tool_search": summary = (input.query as string) || ""; break;
    case "web_search": summary = (input.query as string) || ""; break;
    case "web_fetch": summary = (input.url as string) || ""; break;
    default: summary = JSON.stringify(input).slice(0, 80);
  }

  return (
    <motion.div initial={{ opacity: 0, y: 4 }} animate={{ opacity: 1, y: 0 }}
      className={clsx("rounded-lg border overflow-hidden", denied ? "border-[#ff4444]/10 bg-[#ff4444]/[0.02]" : "border-white/[0.04] bg-white/[0.01]")}>
      <button onClick={() => setExpanded(!expanded)}
        className="w-full flex items-center gap-3 px-4 py-2.5 hover:bg-white/[0.02] transition-colors text-left">
        <span className="opacity-60 shrink-0">{getToolIcon(cat, denied ? "#ff4444" : colors.iconColor)}</span>
        <span className={clsx("text-[10px] font-semibold shrink-0", denied ? "text-[#ff4444]" : colors.text)}>{tool.tool_name}</span>
        {denied && <span className="text-[9px] font-bold text-[#ff4444] bg-[#ff4444]/8 rounded px-1 py-0.5">DENIED</span>}
        {isPending && <span className="text-[9px] text-[#ffaa00] animate-pulse">running</span>}
        <span className="text-[9px] text-[#888] truncate flex-1">{denied ? tool.deny_reason : summary}</span>
        <span className="text-[9px] text-[#777] tabular-nums shrink-0">{fmtTime(tool.ts)}</span>
        {tool.duration_ms != null && <span className="text-[9px] text-[#888] tabular-nums shrink-0">{fmtDuration(tool.duration_ms)}</span>}
        <Chevron open={expanded} size={8} />
      </button>
      {expanded && (
        <motion.div initial={{ height: 0 }} animate={{ height: "auto" }} className="border-t border-white/[0.04] overflow-hidden">
          <div className="p-3 space-y-2.5">
            <StyledToolOutput tool={tool} />
            {/* Show raw input if no styled output rendered it */}
            {tool.input_data && cat !== "bash" && cat !== "todo" && (
              <details className="group">
                <summary className="text-[9px] text-[#777] cursor-pointer hover:text-[#666] transition-colors">raw input</summary>
                <pre className="mt-1 text-[9px] text-[#888] bg-black/20 rounded p-2 border border-[#1a1a1a] whitespace-pre-wrap break-all max-h-[200px] overflow-y-auto">
                  {JSON.stringify(tool.input_data, null, 2)}
                </pre>
              </details>
            )}
          </div>
        </motion.div>
      )}
    </motion.div>
  );
}

/* ── Usage Tick ── */
function UsageTick({ data, ts }: { data: { input_tokens: number; output_tokens: number; total_input: number; total_output: number; cache_read: number }; ts: string }) {
  const fmt = (n: number) => n >= 1_000_000 ? `${(n / 1_000_000).toFixed(1)}M` : n >= 1_000 ? `${(n / 1_000).toFixed(1)}k` : String(n);
  return (
    <div className="flex items-center gap-2 px-4 py-1 text-[9px] text-[#777]">
      <svg width="8" height="8" viewBox="0 0 8 8" fill="none" stroke="#44ccdd" strokeWidth="1" opacity="0.3">
        <rect x="0.5" y="4" width="1.5" height="3.5" rx="0.3" /><rect x="3" y="2" width="1.5" height="5.5" rx="0.3" /><rect x="5.5" y="0.5" width="1.5" height="7" rx="0.3" />
      </svg>
      <span>{fmt(data.total_input)}↓ {fmt(data.total_output)}↑</span>
      {data.cache_read > 0 && <span>cache:{fmt(data.cache_read)}</span>}
      <span className="ml-auto tabular-nums">{fmtTime(ts)}</span>
    </div>
  );
}

/* ── Control ── */
function ControlMessage({ text, ts }: { text: string; ts: string }) {
  return (
    <div className="flex items-center gap-2 px-4 py-2">
      <div className="flex-1 h-px bg-[#ffaa00]/10" />
      <div className="flex items-center gap-1.5 text-[9px] text-[#ffaa00]/70">
        <svg width="10" height="10" viewBox="0 0 10 10" fill="none" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round"><polyline points="2 4 5 7 2 10" /><line x1="6" y1="10" x2="9" y2="10" /></svg>
        {text}
        <span className="text-[#777] tabular-nums">{fmtTime(ts)}</span>
      </div>
      <div className="flex-1 h-px bg-[#ffaa00]/10" />
    </div>
  );
}

/* ── Milestone ── */
function MilestoneCard({ label, detail, color, ts }: { label: string; detail: string; color: string; ts: string }) {
  const isUrl = detail && /^https?:\/\//.test(detail);
  return (
    <motion.div initial={{ opacity: 0, scale: 0.95 }} animate={{ opacity: 1, scale: 1 }} className="flex items-center gap-2 px-4 py-2">
      <div className="flex-1 h-px" style={{ background: `${color}15` }} />
      <div className="flex items-center gap-2 px-3 py-1.5 rounded-full border" style={{ borderColor: `${color}20`, background: `${color}06` }}>
        <span className="h-1.5 w-1.5 rounded-full" style={{ background: color }} />
        <span className="text-[10px] font-semibold" style={{ color }}>{label}</span>
        {detail && (isUrl ? (
          <a
            href={detail}
            target="_blank"
            rel="noopener noreferrer"
            className="text-[9px] text-[#88ccff] hover:text-[#aaddff] underline underline-offset-2 max-w-[300px] truncate"
          >
            {detail.includes("/pull/") ? `PR #${detail.split("/").pop()}` : detail}
          </a>
        ) : (
          <span className="text-[9px] text-[#666] max-w-[300px] truncate">{detail}</span>
        ))}
        <span className="text-[9px] text-[#777] tabular-nums">{fmtTime(ts)}</span>
      </div>
      <div className="flex-1 h-px" style={{ background: `${color}15` }} />
    </motion.div>
  );
}

/* ── Divider ── */
function DividerCard({ label }: { label: string }) {
  return (
    <div className="flex items-center gap-3 px-4 py-1.5">
      <div className="flex-1 terminal-hr" />
      <span className="text-[9px] text-[#777] uppercase tracking-wider">{label}</span>
      <div className="flex-1 terminal-hr" />
    </div>
  );
}

/* ── Run Started ── */
function RunStartedCard({ model, branch, baseBranch, prompt, budget, duration, ts }: {
  model: string; branch: string; baseBranch: string; prompt: string; budget: number; duration: number; ts: string;
}) {
  const [showPrompt, setShowPrompt] = useState(false);
  return (
    <motion.div initial={{ opacity: 0, scale: 0.95 }} animate={{ opacity: 1, scale: 1 }}>
      {/* Milestone line */}
      <div className="flex items-center gap-2 px-4 py-2">
        <div className="flex-1 h-px bg-[#88ccff]/10" />
        <div className="flex items-center gap-2 px-3 py-1.5 rounded-full border border-[#88ccff]/20 bg-[#88ccff]/[0.04]">
          <span className="h-1.5 w-1.5 rounded-full bg-[#88ccff]" />
          <span className="text-[10px] font-semibold text-[#88ccff]">Run Started</span>
          <span className="text-[9px] text-[#666]">{model} · {branch}</span>
          {baseBranch !== "main" && <span className="text-[9px] text-[#666]">from {baseBranch}</span>}
          {budget > 0 && <span className="text-[9px] text-[#666]">${budget}</span>}
          {duration > 0 && <span className="text-[9px] text-[#666]">{duration}m</span>}
          <span className="text-[9px] text-[#777] tabular-nums">{fmtTime(ts)}</span>
        </div>
        <div className="flex-1 h-px bg-[#88ccff]/10" />
      </div>
      {/* Prompt display */}
      {prompt && (
        <div className="mx-4 mb-2">
          <button
            onClick={() => setShowPrompt(!showPrompt)}
            className="w-full flex items-center gap-2 px-3 py-2 rounded-lg border border-[#88ccff]/10 bg-[#88ccff]/[0.02] hover:bg-[#88ccff]/[0.04] transition-colors text-left"
          >
            <svg width="12" height="12" viewBox="0 0 12 12" fill="none" stroke="#88ccff" strokeWidth="1" strokeLinecap="round" className="shrink-0 opacity-50">
              <path d="M2 3h8M2 6h5M2 9h7" />
            </svg>
            <span className="text-[10px] text-[#88ccff]/70 uppercase tracking-wider shrink-0">Prompt</span>
            {!showPrompt && <span className="text-[10px] text-[#999] truncate flex-1">{prompt.slice(0, 120)}</span>}
            <Chevron open={showPrompt} size={8} />
          </button>
          {showPrompt && (
            <motion.div initial={{ height: 0, opacity: 0 }} animate={{ height: "auto", opacity: 1 }} className="overflow-hidden">
              <div className="mt-1 px-3 py-2.5 rounded-lg bg-black/20 border border-[#88ccff]/10 text-[10px] text-[#bbb] whitespace-pre-wrap break-words leading-relaxed max-h-[300px] overflow-y-auto">
                {prompt}
              </div>
            </motion.div>
          )}
        </div>
      )}
    </motion.div>
  );
}

/* ═══════════════════════════════════════
   MAIN DISPATCHER
   ═══════════════════════════════════════ */

export function GroupedEventCard({ event, isLast = false }: { event: GroupedEvent; isLast?: boolean }) {
  switch (event.type) {
    case "llm_message":
      return <LLMMessageCard role={event.role} text={event.text} thinking={event.thinking} ts={event.ts} isLast={isLast} />;
    case "tool_group":
      return <ReadGroupCard tools={event.tools} ts={event.ts} totalDuration={event.totalDuration} label={event.label} />;
    case "edit_group":
      return <EditGroupCard tools={event.tools} ts={event.ts} totalDuration={event.totalDuration} />;
    case "bash_group":
      return <BashGroupCard tools={event.tools} ts={event.ts} totalDuration={event.totalDuration} />;
    case "playwright_group":
      return <PlaywrightGroupCard tools={event.tools} ts={event.ts} totalDuration={event.totalDuration} />;
    case "agent_run":
      return <AgentRunCard tool={event.tool} childTools={event.childTools} finalText={event.finalText} ts={event.ts} />;
    case "single_tool":
      return <SingleToolCard tool={event.tool} />;
    case "usage_tick":
      return <UsageTick data={event.data} ts={event.ts} />;
    case "run_started":
      return <RunStartedCard model={event.model} branch={event.branch} baseBranch={event.baseBranch} prompt={event.prompt} budget={event.budget} duration={event.duration} ts={event.ts} />;
    case "control":
      return <ControlMessage text={event.text} ts={event.ts} />;
    case "milestone":
      return <MilestoneCard label={event.label} detail={event.detail} color={event.color} ts={event.ts} />;
    case "divider":
      return <DividerCard label={event.label} />;
    default:
      return null;
  }
}
