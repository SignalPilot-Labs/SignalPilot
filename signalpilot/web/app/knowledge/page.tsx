"use client";

import { useState, useEffect, useCallback, useRef, useMemo, type ReactNode } from "react";
import useSWR from "swr";
import {
  RefreshCw,
  Plus,
  ChevronRight,
  ChevronDown,
  Eye,
  Pencil,
  Clock,
  Archive,
  CheckCircle2,
  Loader2,
  X,
} from "lucide-react";
import {
  createKnowledgeDoc,
  updateKnowledgeDoc,
  archiveKnowledgeDoc,
  approveKnowledgeDoc,
  getKnowledgeDoc,
  getConnections,
  getProjects,
} from "@/lib/api";
import {
  useKnowledgeDocs,
  useKnowledgeUsage,
  useKnowledgeEdits,
  invalidateKnowledge,
  SWR_KEYS,
} from "@/lib/hooks/use-gateway-data";
import type { KnowledgeDoc, KnowledgeEdit } from "@/lib/types";
import { useToast } from "@/components/ui/toast";
import { PageLoader } from "@/components/ui/page-loader";
import { EmptyList, EmptyState } from "@/components/ui/empty-states";
import { PageHeader, TerminalBar } from "@/components/ui/page-header";
import { ConfirmDialog } from "@/components/ui/confirm-dialog";
import { TimeAgo } from "@/components/ui/time-ago";

// ── Constants ────────────────────────────────────────────────────────────────

const KB_EXPANDED_KEY = "kb_expanded";

const CATEGORY_LABELS: Record<KnowledgeDoc["category"], string> = {
  understanding: "understanding",
  conventions: "conventions",
  decisions: "decisions",
  "domain-rules": "domain-rules",
  debugging: "debugging",
  quirks: "quirks",
};

const SCOPE_CATEGORIES: Record<KnowledgeDoc["scope"], KnowledgeDoc["category"][]> = {
  org: ["understanding", "conventions"],
  project: ["understanding", "conventions", "decisions", "domain-rules", "debugging"],
  connection: ["quirks"],
};

// ── Inline diff helper ────────────────────────────────────────────────────────

function renderDiff(before: string, after: string) {
  const beforeLines = before.split("\n");
  const afterLines = after.split("\n");
  const maxLen = Math.max(beforeLines.length, afterLines.length);
  const rows: { before: string | null; after: string | null }[] = [];
  for (let i = 0; i < maxLen; i++) {
    const b = i < beforeLines.length ? beforeLines[i] : null;
    const a = i < afterLines.length ? afterLines[i] : null;
    rows.push({ before: b, after: a });
  }
  return rows;
}

function formatBytes(bytes: number): string {
  if (bytes < 1024) return `${bytes}B`;
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)}KB`;
  return `${(bytes / (1024 * 1024)).toFixed(1)}MB`;
}

// ── Tree helpers ─────────────────────────────────────────────────────────────

type TreeGroup = {
  key: string;
  label: string;
  docs: KnowledgeDoc[];
  children: TreeGroup[];
};

function buildTree(docs: KnowledgeDoc[]): TreeGroup[] {
  const orgDocs = docs.filter((d) => d.scope === "org");
  const projectDocs = docs.filter((d) => d.scope === "project");
  const connectionDocs = docs.filter((d) => d.scope === "connection");

  function groupByCategory(items: KnowledgeDoc[], prefix: string): TreeGroup[] {
    const map = new Map<string, KnowledgeDoc[]>();
    for (const doc of items) {
      const existing = map.get(doc.category) ?? [];
      existing.push(doc);
      map.set(doc.category, existing);
    }
    return Array.from(map.entries()).map(([cat, catDocs]) => ({
      key: `${prefix}:${cat}`,
      label: cat,
      docs: catDocs,
      children: [],
    }));
  }

  function groupByRef(items: KnowledgeDoc[], scopeType: string): TreeGroup[] {
    const map = new Map<string, KnowledgeDoc[]>();
    for (const doc of items) {
      const ref = doc.scope_ref ?? "_unknown";
      const existing = map.get(ref) ?? [];
      existing.push(doc);
      map.set(ref, existing);
    }
    return Array.from(map.entries()).map(([ref, refDocs]) => ({
      key: `${scopeType}:${ref}`,
      label: ref,
      docs: [],
      children: groupByCategory(refDocs, `${scopeType}:${ref}`),
    }));
  }

  const root: TreeGroup[] = [];

  if (orgDocs.length > 0) {
    root.push({
      key: "scope:org",
      label: "org",
      docs: [],
      children: groupByCategory(orgDocs, "scope:org"),
    });
  }

  if (projectDocs.length > 0) {
    root.push({
      key: "scope:project",
      label: "projects",
      docs: [],
      children: groupByRef(projectDocs, "proj"),
    });
  }

  if (connectionDocs.length > 0) {
    root.push({
      key: "scope:connection",
      label: "connections",
      docs: [],
      children: groupByRef(connectionDocs, "conn"),
    });
  }

  return root;
}

// ── TreeNode component ────────────────────────────────────────────────────────

function TreeNode({
  group,
  docs,
  depth,
  selectedId,
  expanded,
  onToggle,
  onSelect,
  backlinkCounts,
}: {
  group: TreeGroup;
  docs: KnowledgeDoc[];
  depth: number;
  selectedId: string | null;
  expanded: Set<string>;
  onToggle: (key: string) => void;
  onSelect: (id: string) => void;
  backlinkCounts: Map<string, number>;
}) {
  const isOpen = expanded.has(group.key);
  const indent = depth * 12;
  const hasChildren = group.children.length > 0 || group.docs.length > 0;

  return (
    <div>
      {/* Group header — only shown when there are children or docs to reveal */}
      {hasChildren && (
        <button
          onClick={() => onToggle(group.key)}
          aria-label={`${isOpen ? "collapse" : "expand"} ${group.label}`}
          aria-expanded={isOpen}
          className="w-full flex items-center gap-1.5 px-2 py-1 text-[11px] text-[var(--color-text-dim)] hover:text-[var(--color-text)] transition-colors uppercase tracking-[0.12em] text-left"
          style={{ paddingLeft: `${8 + indent}px` }}
        >
          {isOpen ? (
            <ChevronDown className="w-2.5 h-2.5 flex-shrink-0" strokeWidth={1.5} />
          ) : (
            <ChevronRight className="w-2.5 h-2.5 flex-shrink-0" strokeWidth={1.5} />
          )}
          {group.label}
        </button>
      )}

      {isOpen && (
        <>
          {group.children.map((child) => (
            <TreeNode
              key={child.key}
              group={child}
              docs={docs}
              depth={depth + 1}
              selectedId={selectedId}
              expanded={expanded}
              onToggle={onToggle}
              onSelect={onSelect}
              backlinkCounts={backlinkCounts}
            />
          ))}
          {group.docs.map((doc) => {
            const isSelected = selectedId === doc.id;
            return (
              <button
                key={doc.id}
                onClick={() => onSelect(doc.id)}
                className={`w-full flex items-center justify-between px-2 py-1 text-[12px] transition-colors text-left border-l-2 ${
                  isSelected
                    ? "bg-[var(--color-bg-hover)] text-[var(--color-success)] border-[var(--color-success)]"
                    : "text-[var(--color-text-muted)] hover:text-[var(--color-text)] hover:bg-[var(--color-bg-hover)]/60 border-transparent"
                }`}
                style={{ paddingLeft: `${20 + indent}px` }}
              >
                <span className="flex items-center gap-1 truncate flex-1 min-w-0">
                  {doc.status === "pending" && (
                    <span className="w-1.5 h-1.5 flex-shrink-0 bg-[var(--color-warning)]" />
                  )}
                  <span className="truncate">{doc.title}</span>
                </span>
                {(() => {
                  const n = backlinkCounts.get(doc.id) ?? 0;
                  return n > 0 ? (
                    <span
                      className="text-[10px] tabular-nums text-[var(--color-text-dim)] flex-shrink-0 ml-1"
                      title={`${n} backlink${n === 1 ? "" : "s"}`}
                      aria-label={`${n} backlink${n === 1 ? "" : "s"}`}
                    >
                      ↩ {n}
                    </span>
                  ) : null;
                })()}
                <span className="text-[10px] tabular-nums text-[var(--color-text-dim)] flex-shrink-0 ml-1">
                  {doc.view_count > 0 ? doc.view_count : ""}
                </span>
              </button>
            );
          })}
        </>
      )}
    </div>
  );
}

// ── UsageBar component ────────────────────────────────────────────────────────

function UsageBar({ usedBytes, limitBytes }: { usedBytes: number; limitBytes: number }) {
  if (limitBytes === 0) return null;
  const pct = Math.min(1, usedBytes / limitBytes);
  const fillColor =
    pct >= 0.9 ? "var(--color-error)" : pct >= 0.7 ? "var(--color-warning)" : "var(--color-success)";
  return (
    <div className="p-3 border-t border-[var(--color-border)] bg-[var(--color-bg-card)]">
      <div className="flex justify-between text-[10px] text-[var(--color-text-dim)] tabular-nums mb-1.5 tracking-wider">
        <span>{formatBytes(usedBytes)}</span>
        <span>{formatBytes(limitBytes)}</span>
      </div>
      <div className="h-1.5 bg-[var(--color-bg)] border border-[var(--color-border)]">
        <div
          className="h-full transition-all"
          style={{ width: `${(pct * 100).toFixed(1)}%`, backgroundColor: fillColor }}
        />
      </div>
    </div>
  );
}

// ── HistoryModal component ────────────────────────────────────────────────────

function HistoryModal({
  doc,
  edits,
  onClose,
  onRevert,
}: {
  doc: KnowledgeDoc;
  edits: KnowledgeEdit[];
  onClose: () => void;
  onRevert: (edit: KnowledgeEdit) => void;
}) {
  const [diffEdit, setDiffEdit] = useState<KnowledgeEdit | null>(null);
  const [confirmRevert, setConfirmRevert] = useState<KnowledgeEdit | null>(null);
  const closeButtonRef = useRef<HTMLButtonElement>(null);

  // Esc-to-close
  useEffect(() => {
    function handleKey(e: KeyboardEvent) {
      if (e.key === "Escape") {
        e.stopPropagation();
        onClose();
      }
    }
    window.addEventListener("keydown", handleKey);
    return () => window.removeEventListener("keydown", handleKey);
  }, [onClose]);

  // Focus close button on open
  useEffect(() => {
    closeButtonRef.current?.focus();
  }, []);

  return (
    <div
      className="fixed inset-0 z-[80] flex items-center justify-center bg-black/70 !ml-0"
      onClick={onClose}
    >
      <div
        role="dialog"
        aria-modal="true"
        aria-label="edit history"
        className="w-[720px] max-h-[80vh] bg-[var(--color-bg-card)] border border-[var(--color-border)] flex flex-col animate-scale-in"
        onClick={(e) => e.stopPropagation()}
      >
        <div className="flex items-center justify-between px-5 py-3 border-b border-[var(--color-border)]">
          <span className="text-[12px] text-[var(--color-text-dim)] uppercase tracking-[0.15em]">
            edit history — {doc.title}
          </span>
          <button
            ref={closeButtonRef}
            onClick={onClose}
            aria-label="close history"
            className="text-[var(--color-text-dim)] hover:text-[var(--color-text)] transition-colors"
          >
            <X className="w-3.5 h-3.5" strokeWidth={1.5} />
          </button>
        </div>

        <div className="overflow-y-auto flex-1">
          {edits.length === 0 ? (
            <div className="px-5 py-8 text-center text-[12px] text-[var(--color-text-dim)] tracking-wider">
              no edit history
            </div>
          ) : (
            edits.map((edit) => {
              const byteDelta = doc.bytes - edit.bytes_before;
              const isDiffOpen = diffEdit?.id === edit.id;
              return (
                <div key={edit.id} className="border-b border-[var(--color-border)] last:border-b-0">
                  <div className="flex items-center gap-3 px-5 py-3">
                    <div className="flex-1 min-w-0">
                      <div className="flex items-center gap-2 flex-wrap">
                        <TimeAgo timestamp={edit.edited_at} className="text-[12px] text-[var(--color-text-dim)] tabular-nums" />
                        <span className="px-1 py-0.5 border border-[var(--color-border)] text-[11px] text-[var(--color-text-dim)] tracking-wider">
                          {edit.edit_kind}
                        </span>
                        {byteDelta !== 0 && (
                          <span className={`text-[11px] tabular-nums tracking-wider ${byteDelta > 0 ? "text-[var(--color-success)]" : "text-[var(--color-error)]"}`}>
                            {byteDelta > 0 ? "+" : ""}{byteDelta}B
                          </span>
                        )}
                        {edit.edited_by && (
                          <span className="text-[11px] text-[var(--color-text-dim)] tracking-wider">
                            by {edit.edited_by}
                          </span>
                        )}
                      </div>
                    </div>
                    <div className="flex items-center gap-2">
                      <button
                        onClick={() => setDiffEdit(isDiffOpen ? null : edit)}
                        className="px-2 py-1 text-[11px] text-[var(--color-text-dim)] hover:text-[var(--color-text)] border border-[var(--color-border)] hover:border-[var(--color-border-hover)] transition-all tracking-wider"
                      >
                        {isDiffOpen ? "hide" : "diff"}
                      </button>
                      <button
                        onClick={() => setConfirmRevert(edit)}
                        className="px-2 py-1 text-[11px] text-[var(--color-warning)] border border-[var(--color-warning)]/20 hover:bg-[var(--color-warning)]/5 transition-colors tracking-wider"
                      >
                        revert
                      </button>
                    </div>
                  </div>

                  {isDiffOpen && (
                    <div className="px-5 pb-3 animate-fade-in">
                      <div className="grid grid-cols-2 gap-2 text-[11px]">
                        <div>
                          <div className="px-2 py-1 border border-[var(--color-border)] bg-[var(--color-bg)] mb-1 text-[var(--color-text-dim)] tracking-wider uppercase">before</div>
                          <div className="border border-[var(--color-border)] max-h-48 overflow-y-auto">
                            {renderDiff(edit.body_before, doc.body ?? "").map((row, i) => (
                              <div
                                key={i}
                                className={`px-2 py-0.5 font-mono whitespace-pre-wrap break-all leading-relaxed ${
                                  row.after === null ? "bg-[var(--color-error)]/10" : ""
                                }`}
                              >
                                {row.before ?? ""}
                              </div>
                            ))}
                          </div>
                        </div>
                        <div>
                          <div className="px-2 py-1 border border-[var(--color-border)] bg-[var(--color-bg)] mb-1 text-[var(--color-text-dim)] tracking-wider uppercase">current</div>
                          <div className="border border-[var(--color-border)] max-h-48 overflow-y-auto">
                            {renderDiff(edit.body_before, doc.body ?? "").map((row, i) => (
                              <div
                                key={i}
                                className={`px-2 py-0.5 font-mono whitespace-pre-wrap break-all leading-relaxed ${
                                  row.before === null ? "bg-[var(--color-success)]/10" : ""
                                }`}
                              >
                                {row.after ?? ""}
                              </div>
                            ))}
                          </div>
                        </div>
                      </div>
                    </div>
                  )}
                </div>
              );
            })
          )}
        </div>
      </div>

      <ConfirmDialog
        open={confirmRevert !== null}
        title="revert document"
        message={`revert "${doc.title}" to this earlier version? the current body will be replaced.`}
        confirmLabel="revert"
        variant="danger"
        onConfirm={() => {
          if (confirmRevert) {
            onRevert(confirmRevert);
            setConfirmRevert(null);
            onClose();
          }
        }}
        onCancel={() => setConfirmRevert(null)}
      />
    </div>
  );
}

// ── CreateDocForm component ───────────────────────────────────────────────────

function CreateDocForm({
  onCancel,
  onCreated,
}: {
  onCancel: () => void;
  onCreated: (doc: KnowledgeDoc) => void;
}) {
  const { toast } = useToast();
  const [scope, setScope] = useState<KnowledgeDoc["scope"]>("org");
  const [scopeRef, setScopeRef] = useState("");
  const [category, setCategory] = useState<KnowledgeDoc["category"]>("understanding");
  const [title, setTitle] = useState("");
  const [body, setBody] = useState("");
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [projects, setProjects] = useState<string[]>([]);
  const [connections, setConnections] = useState<string[]>([]);

  useEffect(() => {
    getProjects().then((p) => setProjects(p.map((x) => x.name))).catch(() => {});
    getConnections().then((c) => setConnections(c.map((x) => x.name))).catch(() => {});
  }, []);

  const allowedCategories = SCOPE_CATEGORIES[scope];

  useEffect(() => {
    if (!allowedCategories.includes(category)) {
      setCategory(allowedCategories[0]);
    }
  }, [scope, allowedCategories, category]);

  async function handleSubmit(e: React.FormEvent) {
    e.preventDefault();
    setSubmitting(true);
    setError(null);
    try {
      const doc = await createKnowledgeDoc({
        scope,
        scope_ref: scope === "org" ? null : (scopeRef || null),
        category,
        title: title.trim(),
        body,
      });
      toast("doc created", "success");
      onCreated(doc);
    } catch (err) {
      const msg = err instanceof Error ? err.message : "unknown error";
      if (msg.includes("409")) {
        setError("a doc with this title already exists in this scope/category");
      } else if (msg.includes("403")) {
        toast("admin scope required", "error");
      } else {
        setError(msg);
      }
    } finally {
      setSubmitting(false);
    }
  }

  const refs = scope === "project" ? projects : scope === "connection" ? connections : [];

  return (
    <div className="border border-[var(--color-border)] bg-[var(--color-bg-card)] p-5 mb-4 animate-fade-in">
      <div className="flex items-center justify-between mb-4">
        <span className="text-[12px] text-[var(--color-text-dim)] uppercase tracking-[0.15em]">new doc</span>
        <button onClick={onCancel} className="text-[var(--color-text-dim)] hover:text-[var(--color-text)] transition-colors">
          <X className="w-3.5 h-3.5" strokeWidth={1.5} />
        </button>
      </div>

      <form onSubmit={handleSubmit} className="space-y-3">
        <div className="grid grid-cols-3 gap-3">
          <div>
            <label className="block text-[11px] text-[var(--color-text-dim)] mb-1 tracking-wider">scope</label>
            <select
              value={scope}
              onChange={(e) => setScope(e.target.value as KnowledgeDoc["scope"])}
              className="w-full px-3 py-2 bg-[var(--color-bg-input)] border border-[var(--color-border)] text-xs focus:outline-none focus:border-[var(--color-text-dim)]"
            >
              <option value="org">org</option>
              <option value="project">project</option>
              <option value="connection">connection</option>
            </select>
          </div>
          <div>
            <label className="block text-[11px] text-[var(--color-text-dim)] mb-1 tracking-wider">scope ref</label>
            {scope === "org" ? (
              <input
                disabled
                value="—"
                className="w-full px-3 py-2 bg-[var(--color-bg-input)] border border-[var(--color-border)] text-xs opacity-40"
              />
            ) : refs.length > 0 ? (
              <select
                value={scopeRef}
                onChange={(e) => setScopeRef(e.target.value)}
                className="w-full px-3 py-2 bg-[var(--color-bg-input)] border border-[var(--color-border)] text-xs focus:outline-none focus:border-[var(--color-text-dim)]"
              >
                <option value="">select...</option>
                {refs.map((r) => <option key={r} value={r}>{r}</option>)}
              </select>
            ) : (
              <input
                type="text"
                value={scopeRef}
                onChange={(e) => setScopeRef(e.target.value)}
                placeholder={scope === "project" ? "project name" : "connection name"}
                className="w-full px-3 py-2 bg-[var(--color-bg-input)] border border-[var(--color-border)] text-xs focus:outline-none focus:border-[var(--color-text-dim)]"
              />
            )}
          </div>
          <div>
            <label className="block text-[11px] text-[var(--color-text-dim)] mb-1 tracking-wider">category</label>
            <select
              value={category}
              onChange={(e) => setCategory(e.target.value as KnowledgeDoc["category"])}
              className="w-full px-3 py-2 bg-[var(--color-bg-input)] border border-[var(--color-border)] text-xs focus:outline-none focus:border-[var(--color-text-dim)]"
            >
              {allowedCategories.map((c) => (
                <option key={c} value={c}>{c}</option>
              ))}
            </select>
          </div>
        </div>
        <div>
          <label className="block text-[11px] text-[var(--color-text-dim)] mb-1 tracking-wider">
            title <span className="text-[var(--color-text-dim)] opacity-60">(slug: ^[a-z0-9-]+$)</span>
          </label>
          <input
            type="text"
            value={title}
            onChange={(e) => setTitle(e.target.value)}
            required
            placeholder="e.g. postgres-naming-conventions"
            className="w-full px-3 py-2 bg-[var(--color-bg-input)] border border-[var(--color-border)] text-xs focus:outline-none focus:border-[var(--color-text-dim)] tracking-wide"
          />
        </div>
        <div>
          <label className="block text-[11px] text-[var(--color-text-dim)] mb-1 tracking-wider">body</label>
          <textarea
            value={body}
            onChange={(e) => setBody(e.target.value)}
            rows={8}
            className="w-full px-3 py-2 bg-[var(--color-bg-input)] border border-[var(--color-border)] text-xs focus:outline-none focus:border-[var(--color-text-dim)] font-mono resize-y"
          />
        </div>
        {error && (
          <p className="text-[12px] text-[var(--color-error)] tracking-wider">{error}</p>
        )}
        <div className="flex items-center gap-2 pt-1">
          <button
            type="submit"
            disabled={submitting || !title.trim()}
            className="flex items-center gap-2 px-4 py-2 text-[12px] text-[var(--color-success)] border border-[var(--color-success)]/30 hover:bg-[var(--color-success)]/5 transition-colors tracking-wider uppercase disabled:opacity-40"
          >
            {submitting && <Loader2 className="w-3 h-3 animate-spin" />}
            create
          </button>
          <button
            type="button"
            onClick={onCancel}
            className="px-4 py-2 text-[12px] text-[var(--color-text-dim)] hover:text-[var(--color-text)] transition-colors tracking-wider uppercase"
          >
            cancel
          </button>
        </div>
      </form>
    </div>
  );
}

// ── Main page ─────────────────────────────────────────────────────────────────

export default function KnowledgePage() {
  const { toast } = useToast();

  // Page state
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [editMode, setEditMode] = useState(false);
  const [editBuffer, setEditBuffer] = useState("");
  const [expanded, setExpanded] = useState<Set<string>>(() => {
    if (typeof window === "undefined") return new Set(["scope:org"]);
    try {
      const stored = localStorage.getItem(KB_EXPANDED_KEY);
      return stored ? new Set(JSON.parse(stored) as string[]) : new Set(["scope:org"]);
    } catch {
      return new Set(["scope:org"]);
    }
  });
  const [statusFilter, setStatusFilter] = useState<"active" | "pending" | "archived">("active");
  const [searchQ, setSearchQ] = useState("");
  const [historyOpen, setHistoryOpen] = useState(false);
  const [creating, setCreating] = useState(false);
  const [saving, setSaving] = useState(false);
  const [confirmArchive, setConfirmArchive] = useState(false);
  const [confirmApprove, setConfirmApprove] = useState(false);
  const [dirtyConfirm, setDirtyConfirm] = useState(false);
  const [pendingSelectId, setPendingSelectId] = useState<string | null>(null);

  // Data
  const { data: docs, isLoading, mutate: refreshList } = useKnowledgeDocs({ status: statusFilter });
  const { data: usage } = useKnowledgeUsage();
  const { data: pending } = useKnowledgeDocs({ status: "pending" });
  const { data: selectedDoc, mutate: refreshDoc } = useSWR<KnowledgeDoc>(
    selectedId ? SWR_KEYS.knowledgeDoc(selectedId) : null,
    () => getKnowledgeDoc(selectedId!),
    {
      dedupingInterval: 30_000,
      onError: (err) => {
        const msg = err instanceof Error ? err.message : "";
        if (msg.startsWith("404")) {
          setSelectedId(null);
          toast("doc not found — may have been archived", "error");
        }
      },
    },
  );
  const { data: edits, mutate: refreshEdits } = useKnowledgeEdits(historyOpen ? selectedId : null);

  // Initialize editBuffer when entering edit mode or switching docs
  useEffect(() => {
    if (editMode && selectedDoc) {
      setEditBuffer(selectedDoc.body ?? "");
    }
  }, [editMode, selectedDoc?.id]); // eslint-disable-line react-hooks/exhaustive-deps

  // Persist expanded keys to localStorage
  useEffect(() => {
    try {
      localStorage.setItem(KB_EXPANDED_KEY, JSON.stringify(Array.from(expanded)));
    } catch {}
  }, [expanded]);

  // Keyboard shortcuts
  useEffect(() => {
    function handleKey(e: KeyboardEvent) {
      if (e.target instanceof HTMLInputElement || e.target instanceof HTMLTextAreaElement) return;
      if ((e.metaKey || e.ctrlKey) && e.key === "e" && selectedId && !editMode) {
        e.preventDefault();
        setEditMode(true);
      }
    }
    window.addEventListener("keydown", handleKey);
    return () => window.removeEventListener("keydown", handleKey);
  }, [selectedId, editMode]);

  function toggleExpand(key: string) {
    setExpanded((prev) => {
      const next = new Set(prev);
      if (next.has(key)) {
        next.delete(key);
      } else {
        next.add(key);
      }
      return next;
    });
  }

  function handleSelectDoc(id: string) {
    if (editMode && editBuffer !== (selectedDoc?.body ?? "")) {
      setPendingSelectId(id);
      setDirtyConfirm(true);
      return;
    }
    setEditMode(false);
    setSelectedId(id);
  }

  async function handleSave() {
    if (!selectedId) return;
    setSaving(true);
    try {
      await updateKnowledgeDoc(selectedId, editBuffer);
      toast("saved", "success");
      setEditMode(false);
      await Promise.all([refreshDoc(), refreshList(), invalidateKnowledge()]);
    } catch (err) {
      const msg = err instanceof Error ? err.message : "unknown error";
      if (msg.includes("403")) {
        toast("admin scope required", "error");
      } else {
        toast(`save failed: ${msg}`, "error");
      }
    } finally {
      setSaving(false);
    }
  }

  async function handleArchive() {
    if (!selectedId) return;
    try {
      await archiveKnowledgeDoc(selectedId);
      toast("archived", "success");
      setSelectedId(null);
      setEditMode(false);
      await Promise.all([refreshList(), invalidateKnowledge()]);
    } catch (err) {
      const msg = err instanceof Error ? err.message : "unknown error";
      if (msg.includes("403")) {
        toast("admin scope required", "error");
      } else {
        toast(`archive failed: ${msg}`, "error");
      }
    }
  }

  async function handleApprove(id: string) {
    try {
      await approveKnowledgeDoc(id);
      toast("approved", "success");
      if (id === selectedId) {
        setSelectedId(null);
      }
      await Promise.all([refreshList(), invalidateKnowledge()]);
    } catch (err) {
      const msg = err instanceof Error ? err.message : "unknown error";
      if (msg.includes("403")) {
        toast("admin scope required", "error");
      } else {
        toast(`approve failed: ${msg}`, "error");
      }
    }
  }

  async function handleRevert(edit: KnowledgeEdit) {
    if (!selectedId) return;
    try {
      await updateKnowledgeDoc(selectedId, edit.body_before);
      toast("reverted", "success");
      setHistoryOpen(false);
      await Promise.all([refreshDoc(), refreshList(), invalidateKnowledge(), refreshEdits()]);
    } catch (err) {
      const msg = err instanceof Error ? err.message : "unknown error";
      if (msg.includes("403")) {
        toast("admin scope required", "error");
      } else {
        toast(`revert failed: ${msg}`, "error");
      }
    }
  }

  const handleEditKeyDown = useCallback(
    (e: React.KeyboardEvent<HTMLTextAreaElement>) => {
      if ((e.metaKey || e.ctrlKey) && e.key === "s") {
        e.preventDefault();
        handleSave();
      }
      if (e.key === "Escape") {
        if (editBuffer !== (selectedDoc?.body ?? "")) {
          setDirtyConfirm(true);
        } else {
          setEditMode(false);
        }
      }
    },
    [editBuffer, selectedDoc?.body], // eslint-disable-line react-hooks/exhaustive-deps
  );

  // Filter docs client-side by searchQ (substring on title)
  const filteredDocs = (docs ?? []).filter((d) =>
    searchQ ? d.title.toLowerCase().includes(searchQ.toLowerCase()) : true,
  );

  // Build backlink index: target doc id → list of source docs that [[link]] to it.
  // Keyed only on `docs` (unfiltered) so it survives tree search filtering.
  const backlinkIndex = useMemo(() => {
    const all = docs ?? [];
    const idx = new Map<string, KnowledgeDoc[]>();
    const re = /\[\[([^\]\n]+)\]\]/g;
    for (const src of all) {
      if (!src.body) continue;
      const seen = new Set<string>();
      let m: RegExpExecArray | null;
      re.lastIndex = 0;
      while ((m = re.exec(src.body)) !== null) {
        const target = resolveWikilink(m[1], all);
        if (!target || target.id === src.id) continue;
        if (seen.has(target.id)) continue;
        seen.add(target.id);
        const list = idx.get(target.id) ?? [];
        list.push(src);
        idx.set(target.id, list);
      }
    }
    return idx;
  }, [docs]);

  const backlinkCounts = useMemo(
    () => new Map(Array.from(backlinkIndex, ([k, v]) => [k, v.length])),
    [backlinkIndex],
  );

  const tree = buildTree(filteredDocs);
  const pendingCount = pending?.length ?? 0;
  const isFirstLoad = isLoading && (docs ?? []).length === 0;

  if (isFirstLoad) return <PageLoader label="loading knowledge base" />;

  return (
    <div className="p-8 animate-fade-in">
      <PageHeader
        title="knowledge"
        subtitle="base"
        description="agent-readable runbook — org conventions, project decisions, connection quirks"
        actions={
          <div className="flex items-center gap-2">
            <button
              onClick={() => setCreating(true)}
              className="flex items-center gap-2 px-3 py-1.5 text-[12px] text-[var(--color-success)] border border-[var(--color-success)]/30 hover:bg-[var(--color-success)]/5 transition-colors tracking-wider uppercase"
            >
              <Plus className="w-3.5 h-3.5" strokeWidth={1.5} />
              new doc
            </button>
            <button
              onClick={() => { refreshList(); invalidateKnowledge(); }}
              className="flex items-center gap-2 px-3 py-1.5 text-[12px] text-[var(--color-text-dim)] hover:text-[var(--color-text)] transition-colors tracking-wider"
            >
              <RefreshCw className={`w-3.5 h-3.5 ${isLoading ? "animate-spin" : ""}`} strokeWidth={1.5} />
              refresh
            </button>
          </div>
        }
      />

      <TerminalBar path="knowledge --tree">
        <div className="flex items-center gap-6 text-xs">
          <span className="text-[var(--color-text-dim)]">
            docs: <code className="text-[12px] text-[var(--color-text)]">{filteredDocs.length}</code>
          </span>
          {usage && usage.storage_limit_bytes > 0 && (
            <span className="text-[var(--color-text-dim)]">
              bytes: <code className="text-[12px] text-[var(--color-text)] tabular-nums">
                {formatBytes(usage.active_bytes)}/{formatBytes(usage.storage_limit_bytes)}
              </code>
            </span>
          )}
          {pendingCount > 0 && (
            <span className="text-[var(--color-warning)]">
              pending: <code className="text-[12px] tabular-nums">{pendingCount}</code>
            </span>
          )}
        </div>
      </TerminalBar>

      {/* Create form */}
      {creating && (
        <CreateDocForm
          onCancel={() => setCreating(false)}
          onCreated={(doc) => {
            setCreating(false);
            setSelectedId(doc.id);
            invalidateKnowledge();
          }}
        />
      )}

      {/* Pending queue strip */}
      {pendingCount > 0 && statusFilter !== "pending" && (
        <div className="mb-4 border border-[var(--color-warning)]/20 bg-[var(--color-bg-card)] p-3">
          <div className="flex items-center gap-2 mb-2">
            <span className="w-1.5 h-1.5 bg-[var(--color-warning)]" />
            <span className="text-[11px] text-[var(--color-warning)] uppercase tracking-[0.15em]">
              {pendingCount} pending {pendingCount === 1 ? "doc" : "docs"} awaiting approval
            </span>
          </div>
          <div className="flex flex-wrap gap-2">
            {(pending ?? []).slice(0, 5).map((doc) => (
              <div key={doc.id} className="flex items-center gap-2 px-2 py-1 border border-[var(--color-border)] text-[11px]">
                <span className="text-[var(--color-text-dim)] tracking-wider truncate max-w-[200px]">{doc.title}</span>
                {doc.proposed_by_agent && (
                  <span className="text-[var(--color-text-dim)] opacity-60">by {doc.proposed_by_agent}</span>
                )}
                <button
                  onClick={() => handleApprove(doc.id)}
                  className="px-1.5 py-0.5 text-[11px] text-[var(--color-success)] border border-[var(--color-success)]/30 hover:bg-[var(--color-success)]/5 transition-colors uppercase tracking-wider"
                >
                  approve
                </button>
                <button
                  onClick={() => { setSelectedId(doc.id); setConfirmArchive(true); }}
                  className="px-1.5 py-0.5 text-[11px] text-[var(--color-text-dim)] border border-[var(--color-border)] hover:text-[var(--color-error)] hover:border-[var(--color-error)]/30 transition-colors uppercase tracking-wider"
                >
                  archive
                </button>
              </div>
            ))}
            {pendingCount > 5 && (
              <button
                onClick={() => setStatusFilter("pending")}
                className="px-2 py-1 text-[11px] text-[var(--color-text-dim)] border border-[var(--color-border)] hover:border-[var(--color-border-hover)] tracking-wider"
              >
                +{pendingCount - 5} more
              </button>
            )}
          </div>
        </div>
      )}

      {/* Main split layout */}
      <div className="flex border border-[var(--color-border)] bg-[var(--color-bg-card)]" style={{ minHeight: "calc(100vh - 320px)" }}>
        {/* Tree pane */}
        <div className="w-72 flex-shrink-0 border-r border-[var(--color-border)] flex flex-col">
          {/* Search + filter */}
          <div className="p-2 border-b border-[var(--color-border)] space-y-2">
            <input
              type="text"
              placeholder="filter docs..."
              value={searchQ}
              onChange={(e) => setSearchQ(e.target.value)}
              className="w-full px-2 py-1.5 bg-[var(--color-bg-input)] border border-[var(--color-border)] text-[12px] focus:outline-none focus:border-[var(--color-text-dim)] tracking-wide"
            />
            <div className="flex items-center gap-1">
              {(["active", "pending", "archived"] as const).map((s) => (
                <button
                  key={s}
                  onClick={() => setStatusFilter(s)}
                  className={`flex-1 py-1 text-[10px] uppercase tracking-[0.1em] transition-colors border ${
                    statusFilter === s
                      ? "border-[var(--color-text-dim)] text-[var(--color-text)]"
                      : "border-[var(--color-border)] text-[var(--color-text-dim)] hover:text-[var(--color-text-muted)]"
                  }`}
                >
                  {s}
                  {s === "pending" && pendingCount > 0 && (
                    <span className="ml-1 text-[var(--color-warning)]">{pendingCount}</span>
                  )}
                </button>
              ))}
            </div>
          </div>

          {/* Tree */}
          <div className="flex-1 overflow-y-auto py-1">
            {filteredDocs.length === 0 ? (
              <div className="px-4 py-8 text-center text-[12px] text-[var(--color-text-dim)] tracking-wider">
                {searchQ ? "no matches" : "no docs"}
              </div>
            ) : tree.length === 0 ? (
              <div className="px-4 py-8 text-center text-[12px] text-[var(--color-text-dim)] tracking-wider">
                no docs
              </div>
            ) : (
              tree.map((group) => (
                <TreeNode
                  key={group.key}
                  group={group}
                  docs={filteredDocs}
                  depth={0}
                  selectedId={selectedId}
                  expanded={expanded}
                  onToggle={toggleExpand}
                  onSelect={handleSelectDoc}
                />
              ))
            )}
          </div>

          {/* Usage bar */}
          {usage && <UsageBar usedBytes={usage.active_bytes} limitBytes={usage.storage_limit_bytes} />}
        </div>

        {/* Content pane */}
        <div className="flex-1 flex flex-col min-w-0">
          {!selectedId ? (
            <EmptyState
              icon={EmptyList}
              title="select a doc"
              description="choose a document from the tree to view or edit"
            />
          ) : !selectedDoc ? (
            <div className="flex items-center justify-center flex-1">
              <Loader2 className="w-4 h-4 animate-spin text-[var(--color-text-dim)]" />
            </div>
          ) : (
            <>
              {/* Doc header */}
              <div className="px-6 pt-5 pb-3 border-b border-[var(--color-border)]">
                <div className="flex items-start gap-3 flex-wrap">
                  <h2 className="text-base font-light tracking-wide text-[var(--color-text)] leading-snug flex-1 min-w-0">
                    {selectedDoc.title}
                  </h2>
                  <div className="flex items-center gap-2 flex-shrink-0 flex-wrap">
                    <span className="px-1.5 py-0.5 border border-[var(--color-border)] text-[10px] text-[var(--color-text-dim)] tracking-wider">
                      {selectedDoc.scope}{selectedDoc.scope_ref ? `:${selectedDoc.scope_ref}` : ""}
                    </span>
                    <span className="px-1.5 py-0.5 border border-[var(--color-border)] text-[10px] text-[var(--color-text-dim)] tracking-wider">
                      {CATEGORY_LABELS[selectedDoc.category]}
                    </span>
                    {selectedDoc.status !== "active" && (
                      <span className={`px-1.5 py-0.5 border text-[10px] tracking-wider ${
                        selectedDoc.status === "pending"
                          ? "border-[var(--color-warning)]/40 text-[var(--color-warning)]"
                          : "border-[var(--color-text-dim)]/20 text-[var(--color-text-dim)]"
                      }`}>
                        {selectedDoc.status}
                      </span>
                    )}
                    <span className="flex items-center gap-1 text-[10px] text-[var(--color-text-dim)] tabular-nums">
                      <Eye className="w-2.5 h-2.5" strokeWidth={1.5} />
                      {selectedDoc.view_count}
                    </span>
                    <span className="text-[10px] text-[var(--color-text-dim)] tabular-nums">
                      {formatBytes(selectedDoc.bytes)}
                    </span>
                  </div>
                </div>
              </div>

              {/* Body */}
              <div className="flex-1 overflow-y-auto px-6 py-4">
                {editMode ? (
                  <textarea
                    autoFocus
                    value={editBuffer}
                    onChange={(e) => setEditBuffer(e.target.value)}
                    onKeyDown={handleEditKeyDown}
                    className="w-full h-full min-h-[400px] px-0 py-0 bg-transparent border-0 text-[13px] font-mono text-[var(--color-text-muted)] focus:outline-none resize-none leading-relaxed"
                    spellCheck={false}
                  />
                ) : (
                  <>
                    <div className="text-[13px] text-[var(--color-text-muted)] leading-relaxed break-words min-h-[400px]">
                      {selectedDoc.body
                        ? <MarkdownView source={selectedDoc.body} docs={docs ?? []} onNavigate={handleSelectDoc} />
                        : <span className="font-mono text-[var(--color-text-dim)]">— no content —</span>
                      }
                    </div>
                    {(() => {
                      const links = backlinkIndex.get(selectedDoc.id) ?? [];
                      if (links.length === 0) return null;
                      return (
                        <div className="mt-8 pt-4 border-t border-[var(--color-border)]">
                          <h3 className="text-[10px] tracking-wider uppercase text-[var(--color-text-dim)] mb-2 font-normal">
                            backlinks ({links.length})
                          </h3>
                          <ul className="flex flex-col gap-1">
                            {links.map((src) => (
                              <li key={src.id}>
                                <button
                                  type="button"
                                  onClick={() => handleSelectDoc(src.id)}
                                  className="flex items-center gap-2 w-full text-left px-1.5 py-1 text-[12px] text-[var(--color-text-muted)] hover:text-[var(--color-text)] hover:bg-[var(--color-border)]/20 focus-visible:outline-none focus-visible:ring-1 focus-visible:ring-[var(--color-text-dim)] transition-colors bg-transparent border-0 cursor-pointer"
                                  title={`${src.category}/${src.title}`}
                                >
                                  <span className="px-1 py-0.5 border border-[var(--color-border)] text-[10px] text-[var(--color-text-dim)] tracking-wider flex-shrink-0">
                                    {CATEGORY_LABELS[src.category]}
                                  </span>
                                  <span className="truncate">{src.title}</span>
                                </button>
                              </li>
                            ))}
                          </ul>
                        </div>
                      );
                    })()}
                  </>
                )}
              </div>

              {/* Footer actions */}
              <div className="px-6 py-3 border-t border-[var(--color-border)] flex items-center gap-2 flex-wrap">
                {editMode ? (
                  <>
                    <button
                      onClick={handleSave}
                      disabled={saving}
                      className="flex items-center gap-2 px-3 py-1.5 text-[12px] text-[var(--color-success)] border border-[var(--color-success)]/30 hover:bg-[var(--color-success)]/5 transition-colors tracking-wider uppercase disabled:opacity-40"
                    >
                      {saving ? <Loader2 className="w-3 h-3 animate-spin" /> : <CheckCircle2 className="w-3 h-3" strokeWidth={1.5} />}
                      {saving ? "saving..." : "save"}
                    </button>
                    <button
                      onClick={() => {
                        if (editBuffer !== (selectedDoc?.body ?? "")) {
                          setDirtyConfirm(true);
                        } else {
                          setEditMode(false);
                        }
                      }}
                      className="px-3 py-1.5 text-[12px] text-[var(--color-text-dim)] hover:text-[var(--color-text)] transition-colors tracking-wider uppercase"
                    >
                      cancel
                    </button>
                    <span className="text-[10px] text-[var(--color-text-dim)] tracking-wider ml-1">ctrl+S to save — esc to cancel</span>
                  </>
                ) : (
                  <>
                    <button
                      onClick={() => setEditMode(true)}
                      className="flex items-center gap-2 px-3 py-1.5 text-[12px] text-[var(--color-text-dim)] hover:text-[var(--color-text)] border border-[var(--color-border)] hover:border-[var(--color-border-hover)] transition-all tracking-wider uppercase"
                    >
                      <Pencil className="w-3 h-3" strokeWidth={1.5} />
                      edit
                    </button>
                    <button
                      onClick={() => { setHistoryOpen(true); }}
                      className="flex items-center gap-2 px-3 py-1.5 text-[12px] text-[var(--color-text-dim)] hover:text-[var(--color-text)] border border-[var(--color-border)] hover:border-[var(--color-border-hover)] transition-all tracking-wider uppercase"
                    >
                      <Clock className="w-3 h-3" strokeWidth={1.5} />
                      history
                    </button>
                    <button
                      onClick={() => setConfirmArchive(true)}
                      className="flex items-center gap-2 px-3 py-1.5 text-[12px] text-[var(--color-text-dim)] hover:text-[var(--color-error)] border border-[var(--color-border)] hover:border-[var(--color-error)]/30 transition-all tracking-wider uppercase"
                    >
                      <Archive className="w-3 h-3" strokeWidth={1.5} />
                      archive
                    </button>
                    {selectedDoc.status === "pending" && (
                      <button
                        onClick={() => setConfirmApprove(true)}
                        className="flex items-center gap-2 px-3 py-1.5 text-[12px] text-[var(--color-success)] border border-[var(--color-success)]/30 hover:bg-[var(--color-success)]/5 transition-colors tracking-wider uppercase"
                      >
                        <CheckCircle2 className="w-3 h-3" strokeWidth={1.5} />
                        approve
                      </button>
                    )}
                  </>
                )}
              </div>
            </>
          )}
        </div>
      </div>

      {/* History modal */}
      {historyOpen && selectedDoc && (
        <HistoryModal
          doc={selectedDoc}
          edits={edits ?? []}
          onClose={() => setHistoryOpen(false)}
          onRevert={handleRevert}
        />
      )}

      {/* Confirm dialogs */}
      <ConfirmDialog
        open={confirmArchive}
        title="archive document"
        message={selectedDoc ? `archive "${selectedDoc.title}"? this removes it from the active knowledge base.` : "archive this document?"}
        confirmLabel="archive"
        variant="danger"
        onConfirm={() => { setConfirmArchive(false); handleArchive(); }}
        onCancel={() => setConfirmArchive(false)}
      />

      <ConfirmDialog
        open={confirmApprove}
        title="approve document"
        message={selectedDoc ? `approve "${selectedDoc.title}"? it will become active and readable by agents.` : "approve this document?"}
        confirmLabel="approve"
        variant="default"
        onConfirm={() => { setConfirmApprove(false); if (selectedId) handleApprove(selectedId); }}
        onCancel={() => setConfirmApprove(false)}
      />

      <ConfirmDialog
        open={dirtyConfirm}
        title="unsaved changes"
        message="you have unsaved changes. discard and continue?"
        confirmLabel="discard"
        variant="danger"
        onConfirm={() => {
          setDirtyConfirm(false);
          setEditMode(false);
          if (pendingSelectId) {
            setSelectedId(pendingSelectId);
            setPendingSelectId(null);
          }
        }}
        onCancel={() => { setDirtyConfirm(false); setPendingSelectId(null); }}
      />
    </div>
  );
}

// ── Markdown renderer ─────────────────────────────────────────────────────────

const SAFE_URL = /^https?:\/\//;

// Priority order for wikilink resolution when multiple docs share the same title
const CATEGORY_PRIORITY: KnowledgeDoc["category"][] = [
  "understanding", "conventions", "decisions", "domain-rules", "debugging", "quirks",
];

function resolveWikilink(
  target: string,
  docs: KnowledgeDoc[],
): KnowledgeDoc | null {
  const trimmed = target.trim();
  if (!trimmed) return null;

  let catRaw: string | null = null;
  let titleRaw: string;

  const slashIdx = trimmed.indexOf("/");
  if (slashIdx !== -1) {
    catRaw = trimmed.slice(0, slashIdx).toLowerCase();
    titleRaw = trimmed.slice(slashIdx + 1).toLowerCase();
  } else {
    titleRaw = trimmed.toLowerCase();
  }

  const candidates = docs.filter((doc) => {
    if (doc.status !== "active") return false;
    if (catRaw !== null && doc.category.toLowerCase() !== catRaw) return false;
    return doc.title.toLowerCase() === titleRaw;
  });

  if (candidates.length === 0) return null;
  if (candidates.length === 1) return candidates[0];

  // Sort by CATEGORY_PRIORITY index ascending; stable (keeps input order on ties)
  const sorted = candidates.slice().sort((a, b) => {
    const ai = CATEGORY_PRIORITY.indexOf(a.category);
    const bi = CATEGORY_PRIORITY.indexOf(b.category);
    const ap = ai === -1 ? CATEGORY_PRIORITY.length : ai;
    const bp = bi === -1 ? CATEGORY_PRIORITY.length : bi;
    return ap - bp;
  });

  return sorted[0];
}

type RenderCtx = {
  docs: KnowledgeDoc[];
  onNavigate: (id: string) => void;
};

function renderInline(text: string, keyPrefix: string, ctx: RenderCtx): ReactNode[] {
  const nodes: ReactNode[] = [];
  // Pattern order: backtick code, bold, italic (** before *), wikilink, external link, underscore italic
  // Wikilink MUST come before the [label](url) branch so [[x]] is not partially eaten
  const pattern =
    /(`[^`]+`)|(\*\*[^*]+\*\*)|(\*[^*]+\*)|(\[\[[^\]\n]+\]\])|(\[[^\]]+\]\([^)]+\))|(_(?=\S)([^_]+?)(?<=\S)_)/g;
  let last = 0;
  let match: RegExpExecArray | null;
  let idx = 0;
  while ((match = pattern.exec(text)) !== null) {
    if (match.index > last) {
      nodes.push(text.slice(last, match.index));
    }
    const k = `${keyPrefix}-${idx++}`;
    const [full] = match;
    if (full.startsWith("`")) {
      nodes.push(
        <code key={k} className="px-1 py-0.5 bg-[var(--color-bg)] border border-[var(--color-border)] text-[12px]">
          {full.slice(1, -1)}
        </code>,
      );
    } else if (full.startsWith("**")) {
      nodes.push(<strong key={k}>{renderInline(full.slice(2, -2), k, ctx)}</strong>);
    } else if (full.startsWith("*")) {
      nodes.push(<em key={k}>{renderInline(full.slice(1, -1), k, ctx)}</em>);
    } else if (full.startsWith("[[")) {
      const inner = full.slice(2, -2);
      const resolved = resolveWikilink(inner, ctx.docs);
      if (resolved) {
        nodes.push(
          <button
            key={k}
            type="button"
            onClick={() => ctx.onNavigate(resolved.id)}
            className="text-[var(--color-success)] underline decoration-dotted underline-offset-2 hover:opacity-80 bg-transparent border-0 p-0 cursor-pointer"
            title={`${resolved.category}/${resolved.title}`}
          >
            {inner}
          </button>,
        );
      } else {
        nodes.push(
          <span
            key={k}
            className="text-[var(--color-error)] opacity-70 line-through decoration-[var(--color-error)]/40"
            title="broken link — no matching doc"
          >
            {`[[${inner}]]`}
          </span>,
        );
      }
    } else if (full.startsWith("_")) {
      const inner = full.replace(/^_|_$/g, "");
      nodes.push(<em key={k}>{renderInline(inner, k, ctx)}</em>);
    } else if (full.startsWith("[")) {
      const labelMatch = full.match(/^\[([^\]]+)\]\(([^)]+)\)$/);
      if (labelMatch) {
        const [, label, url] = labelMatch;
        if (SAFE_URL.test(url)) {
          nodes.push(
            <a key={k} href={url} className="text-[var(--color-success)] underline" target="_blank" rel="noopener noreferrer">
              {label}
            </a>,
          );
        } else {
          nodes.push(full);
        }
      } else {
        nodes.push(full);
      }
    } else {
      nodes.push(full);
    }
    last = match.index + full.length;
  }
  if (last < text.length) {
    nodes.push(text.slice(last));
  }
  return nodes;
}

function renderMarkdown(src: string, ctx: RenderCtx): ReactNode[] {
  const lines = src.split("\n");
  const out: ReactNode[] = [];
  let i = 0;
  let para: string[] = [];
  let counter = 0;

  const key = () => `md-${counter++}`;

  const flushPara = () => {
    if (para.length === 0) return;
    const k = key();
    out.push(
      <p key={k} className="my-2">
        {renderInline(para.join(" "), k, ctx)}
      </p>,
    );
    para = [];
  };

  while (i < lines.length) {
    const line = lines[i];

    // Fenced code block
    if (line.startsWith("```")) {
      flushPara();
      const codeLines: string[] = [];
      i++;
      while (i < lines.length && !lines[i].startsWith("```")) {
        codeLines.push(lines[i]);
        i++;
      }
      out.push(
        <pre key={key()} className="my-2 p-2 bg-[var(--color-bg)] border border-[var(--color-border)] text-[12px] overflow-x-auto whitespace-pre-wrap">
          {codeLines.join("\n")}
        </pre>,
      );
      i++; // skip closing fence
      continue;
    }

    // Headings
    if (line.startsWith("### ")) {
      flushPara();
      const k = key();
      out.push(<h3 key={k} className="text-[13px] font-semibold text-[var(--color-text)] mt-4 mb-2">{renderInline(line.slice(4), k, ctx)}</h3>);
      i++;
      continue;
    }
    if (line.startsWith("## ")) {
      flushPara();
      const k = key();
      out.push(<h2 key={k} className="text-sm font-semibold text-[var(--color-text)] mt-4 mb-2">{renderInline(line.slice(3), k, ctx)}</h2>);
      i++;
      continue;
    }
    if (line.startsWith("# ")) {
      flushPara();
      const k = key();
      out.push(<h1 key={k} className="text-base font-semibold text-[var(--color-text)] mt-4 mb-2">{renderInline(line.slice(2), k, ctx)}</h1>);
      i++;
      continue;
    }

    // Unordered list — consume the run
    if (/^[-*] /.test(line)) {
      flushPara();
      const items: ReactNode[] = [];
      while (i < lines.length && /^[-*] /.test(lines[i])) {
        const ik = key();
        items.push(<li key={ik}>{renderInline(lines[i].slice(2), ik, ctx)}</li>);
        i++;
      }
      out.push(<ul key={key()} className="list-disc pl-5 my-1">{items}</ul>);
      continue;
    }

    // Ordered list — consume the run
    if (/^\d+\. /.test(line)) {
      flushPara();
      const items: ReactNode[] = [];
      while (i < lines.length && /^\d+\. /.test(lines[i])) {
        const ik = key();
        items.push(<li key={ik}>{renderInline(lines[i].replace(/^\d+\. /, ""), ik, ctx)}</li>);
        i++;
      }
      out.push(<ol key={key()} className="list-decimal pl-5 my-1">{items}</ol>);
      continue;
    }

    // Blank line — paragraph break
    if (line.trim() === "") {
      flushPara();
      i++;
      continue;
    }

    // Default — accumulate paragraph
    para.push(line);
    i++;
  }

  flushPara();
  return out;
}

function MarkdownView({
  source,
  docs,
  onNavigate,
}: {
  source: string;
  docs: KnowledgeDoc[];
  onNavigate: (id: string) => void;
}) {
  const ctx: RenderCtx = { docs, onNavigate };
  return <>{renderMarkdown(source, ctx)}</>;
}
