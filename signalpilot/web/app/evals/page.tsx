"use client";

/**
 * Eval management (/evals).
 *
 * The page displays tasks from an evaluation set.
 * Each task has a Markdown document, a prompt, and grading criteria.
 * A read task uses numeric checks.
 * A write task builds a model on a branch.
 * The grading process checks the model on the branch.
 * The page displays verdicts, coverage, transcripts, accuracy, and regressions.
 */

import { Suspense, useEffect, useMemo, useState } from "react";
import { createPortal } from "react-dom";
import Link from "next/link";
import { useSearchParams } from "next/navigation";
import useSWR, { mutate } from "swr";
import {
  BookOpen,
  BarChart3,
  CheckCircle2,
  ChevronDown,
  ChevronRight,
  Download,
  FlaskConical,
  GitBranch,
  LayoutGrid,
  List,
  Loader2,
  Play,
  Save,
  Search,
  Settings2,
  Square,
  TrendingUp,
  X,
  XCircle,
} from "lucide-react";
import {
  CartesianGrid,
  Line,
  LineChart,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts";
import {
  cancelEvalRun,
  downloadEvalArtifact,
  downloadEvalRunExport,
  getEvalAccuracy,
  getEvalAvailability,
  getEvalConfig,
  getEvalRun,
  getEvalRunProgress,
  getEvalSetupLog,
  listEvalRuns,
  listEvalTasks,
  putEvalConfig,
  startBaselineEvalRun,
  type EvalCheckResult,
  type EvalCoverage,
  type EvalCoverageLayer,
  type EvalGrade,
  type EvalRun,
  type EvalRunTask,
  type EvalTask,
} from "~/lib/api";
import { PageHeader } from "~/components/ui/page-header";
import { useToast } from "~/components/ui/toast";
import { Md, fmtNum } from "./_components/Markdown";
import { RunProgressBar, SandboxPanel } from "./_components/SandboxPanel";
import { ControlDeck } from "./_components/ControlDeck";
import { EvalOnboarding } from "./_components/EvalOnboarding";
import { TranscriptSlideOver } from "./_components/TranscriptView";
import "./evals.css";

/* The following code defines verdicts and badges. */

const VERDICT_STYLE: Record<string, { color: string; label: string }> = {
  CORRECT: { color: "var(--color-success)", label: "correct" },
  PARTIAL: { color: "var(--color-warning, #f5a623)", label: "partial" },
  OFF: { color: "#e5484d", label: "wrong answer" },
  UNKNOWN: { color: "var(--color-warning, #f5a623)", label: "no number" },
  UNGRADED: { color: "var(--color-text-dim)", label: "ungraded" },
  ERROR: { color: "#e5484d", label: "run error" },
  SETUP_FAILED: { color: "#e5484d", label: "setup failed" },
  CANCELLED: { color: "var(--color-text-dim)", label: "cancelled" },
};

function VerdictBadge({ verdict }: { verdict: string | null }) {
  if (!verdict) return <span className="text-xs text-[var(--color-text-dim)]">—</span>;
  const s = VERDICT_STYLE[verdict] ?? { color: "var(--color-text-dim)", label: verdict.toLowerCase() };
  return (
    <span className="text-[11px] tracking-[0.12em] uppercase whitespace-nowrap" style={{ color: s.color }}>
      {s.label}
    </span>
  );
}

function StatusDot({ status }: { status: string }) {
  const color =
    status === "completed" ? "var(--color-success)"
    : status === "failed" ? "#e5484d"
    : status === "cancelled" ? "var(--color-text-dim)"
    : "var(--color-warning, #f5a623)";
  const live = status === "running" || status === "preparing" || status === "cancelling";
  return (
    <span className="inline-flex items-center gap-1.5 text-[11px] uppercase tracking-[0.12em]" style={{ color }}>
      <span className={`w-1.5 h-1.5 rounded-full ${live ? "animate-pulse" : ""}`} style={{ background: color }} />
      {status}
    </span>
  );
}

/** A read task runs queries. A write task builds a model on a branch. */
function ClassBadge({ cls }: { cls: string }) {
  return <span className={`ev-badge ev-badge--${cls === "write" ? "write" : "read"}`}>{cls}</span>;
}

function CheckChips({ results }: { results: EvalCheckResult[] }) {
  if (!results?.length) return null;
  return (
    <span className="inline-flex flex-wrap gap-1.5">
      {results.map((c) => (
        <span
          key={c.name}
          className={`ev-chip ${c.passed ? "ev-chip--pass" : "ev-chip--fail"}`}
          title={
            c.detail
              ? c.detail
              : c.value != null
                ? `${c.name} = ${c.value.toLocaleString()}${c.tolerance != null ? ` ±${Math.round(c.tolerance * 100)}%` : ""}`
                : c.name
          }
        >
          <span className="n">{c.name}</span>
          {c.passed ? "✓" : "✗"}
        </span>
      ))}
    </span>
  );
}

function shortHash(s: string | undefined | null, n = 12): string {
  return s ? s.slice(0, n) : "";
}

/* The following code displays the evaluation set header and configuration. */

function setNameFromUrl(repoUrl: string): string {
  if (!repoUrl) return "no eval set";
  const seg = repoUrl.replace(/\.git$/, "").replace(/[/\\]+$/, "").split(/[/\\]/).pop();
  return seg || repoUrl;
}

function ConfigForm({ onSaved }: { onSaved: () => void }) {
  const { toast } = useToast();
  const { data, mutate } = useSWR("eval-config", getEvalConfig);
  const [form, setForm] = useState({
    repo_url: "",
    repo_installation_id: null as string | null,
    repo_id: null as number | null,
    model: "sonnet",
    max_tasks: 0,
    prompt_preamble: "",
    connection: "",
    notify_emails: "",
    autorun_on_knowledge_add: false,
  });
  const [savingCfg, setSavingCfg] = useState(false);
  const [loaded, setLoaded] = useState(false);

  useEffect(() => {
    if (data && !loaded) {
      setForm({
        repo_url: data.repo_url ?? "",
        repo_installation_id: data.repo_installation_id ?? null,
        repo_id: data.repo_id ?? null,
        model: data.model ?? "sonnet",
        max_tasks: data.max_tasks ?? 0,
        prompt_preamble: data.prompt_preamble ?? "",
        connection: data.connection ?? "",
        notify_emails: (data.notify_emails ?? []).join(", "),
        autorun_on_knowledge_add: data.autorun_on_knowledge_add ?? false,
      });
      setLoaded(true);
    }
  }, [data, loaded]);

  async function save() {
    setSavingCfg(true);
    try {
      await putEvalConfig({
        repo_url: form.repo_url,
        repo_installation_id: form.repo_installation_id,
        repo_id: form.repo_id,
        model: form.model,
        max_tasks: form.max_tasks,
        prompt_preamble: form.prompt_preamble,
        connection: form.connection,
        autorun_on_knowledge_add: form.autorun_on_knowledge_add,
        notify_emails: form.notify_emails
          .split(",")
          .map((e) => e.trim())
          .filter(Boolean),
      });
      await mutate();
      toast("eval config saved", "success");
      onSaved();
    } catch (err) {
      toast(`save failed: ${err instanceof Error ? err.message : "unknown"}`, "error");
    } finally {
      setSavingCfg(false);
    }
  }

  const inputCls =
    "w-full bg-transparent border border-[var(--color-border)] rounded-[10px] px-3 py-2 text-sm text-[var(--color-text)] placeholder:text-[var(--color-text-dim)] focus:border-[var(--color-border-hover)] focus:outline-none";

  return (
    <div className="grid grid-cols-1 md:grid-cols-2 gap-4 mt-4 pt-4 border-t border-[var(--color-border)]">
      <div className="md:col-span-2">
        <label className="block text-xs text-[var(--color-text-muted)] mb-1.5">
          Repo — public git URL, or a local path under /eval-projects (format: eval-format.md)
        </label>
        <input className={inputCls} value={form.repo_url} onChange={(e) => setForm({ ...form, repo_url: e.target.value, repo_installation_id: null, repo_id: null })} placeholder="https://github.com/org/eval-set.git  ·  /eval-projects/northwind" />
      </div>
      <div>
        <label className="block text-xs text-[var(--color-text-muted)] mb-1.5">Model</label>
        <input className={inputCls} value={form.model} onChange={(e) => setForm({ ...form, model: e.target.value })} placeholder="sonnet" />
      </div>
      <div>
        <label className="block text-xs text-[var(--color-text-muted)] mb-1.5">Max tasks per run (0 = all)</label>
        <input className={inputCls} type="number" min={0} max={200} value={form.max_tasks} onChange={(e) => setForm({ ...form, max_tasks: Number(e.target.value) || 0 })} />
      </div>
      <div>
        <label className="block text-xs text-[var(--color-text-muted)] mb-1.5">Connection — warehouse connection the graded agent must use</label>
        <input required className={inputCls} value={form.connection} onChange={(e) => setForm({ ...form, connection: e.target.value })} placeholder="northwind_ro_conn" />
      </div>
      <div>
        <label className="block text-xs text-[var(--color-text-muted)] mb-1.5">Notify emails — comma-separated, alerted on accuracy regressions</label>
        <input className={inputCls} value={form.notify_emails} onChange={(e) => setForm({ ...form, notify_emails: e.target.value })} placeholder="data-team@acme.com, oncall@acme.com" />
      </div>
      <div className="md:col-span-2">
        <label className="block text-xs text-[var(--color-text-muted)] mb-1.5">Prompt preamble — prepended to every task (connection to use, output rules)</label>
        <textarea className={`${inputCls} resize-none`} rows={2} value={form.prompt_preamble} onChange={(e) => setForm({ ...form, prompt_preamble: e.target.value })} placeholder='e.g. "Use the SignalPilot MCP tools with connection northwind_ro_conn."' />
      </div>
      <div className="md:col-span-2">
        <label className="flex items-start gap-2.5 cursor-pointer group">
          <input
            type="checkbox"
            className="mt-0.5 accent-[var(--color-success)]"
            checked={form.autorun_on_knowledge_add}
            onChange={(e) => setForm({ ...form, autorun_on_knowledge_add: e.target.checked })}
          />
          <span>
            <span className="block text-sm text-[var(--color-text)]">
              Autorun whenever a knowledge base entry is added
            </span>
            <span className="block text-xs text-[var(--color-text-muted)] mt-0.5">
              Grades the whole set against the live knowledge base when an entry is approved or
              added. Pending entries don’t trigger it — evaluate those from the knowledge page.
              Repeated additions coalesce into one run every 2 minutes.
            </span>
          </span>
        </label>
      </div>
      <div>
        <button onClick={save} disabled={savingCfg} className="inline-flex items-center gap-2 px-4 py-2 rounded-[10px] text-sm border border-[var(--color-border-hover)] text-[var(--color-text)] hover:bg-[var(--color-bg)] disabled:opacity-40 transition-colors">
          {savingCfg ? <Loader2 className="w-3.5 h-3.5 animate-spin" /> : <Save className="w-3.5 h-3.5" strokeWidth={1.5} />}
          Save config
        </button>
      </div>
    </div>
  );
}

function Hero({
  evalSet,
  repoUrl,
  model,
  runnerEnabled,
  cfgLoaded,
}: {
  evalSet: import("~/lib/api").EvalSetInfo | undefined;
  repoUrl: string;
  model: string;
  runnerEnabled: boolean;
  cfgLoaded: boolean;
}) {
  const [configOpen, setConfigOpen] = useState(false);
  const [starting, setStarting] = useState(false);
  const { toast } = useToast();

  async function runAll() {
    setStarting(true);
    try {
      const run = await startBaselineEvalRun();
      // Refresh the run list immediately to display the started run.
      await mutate("eval-runs");
      toast(`eval run started — ${run.id}`, "success");
    } catch (err) {
      toast(`could not start run: ${err instanceof Error ? err.message : "unknown"}`, "error");
    } finally {
      setStarting(false);
    }
  }

  // Open the configuration panel when the configuration has no repository.
  useEffect(() => {
    if (cfgLoaded && !repoUrl) setConfigOpen(true);
  }, [cfgLoaded, repoUrl]);

  const tasks = evalSet?.tasks;
  const kinds = new Map<string, number>();
  (tasks ?? []).forEach((t) => kinds.set(t.kind, (kinds.get(t.kind) ?? 0) + 1));
  const writes = (tasks ?? []).filter((t) => t.class === "write").length;
  const documented = (tasks ?? []).filter((t) => t.doc).length;

  return (
    <div className="ev-card p-6">
      <div className="flex items-start justify-between gap-4 flex-wrap">
        <div>
          <div className="flex items-center gap-3">
            <FlaskConical className="w-5 h-5 text-[var(--color-success)]" strokeWidth={1.25} />
            <h2 className="text-2xl font-semibold tracking-[-0.01em] text-[var(--color-text)]">{evalSet?.name || setNameFromUrl(repoUrl)}</h2>
          </div>
          <p className="mt-1.5 text-xs text-[var(--color-text-muted)] font-mono">{repoUrl || "configure an eval repo to get started"}</p>
          {evalSet?.description && <p className="mt-1.5 text-sm text-[var(--color-text-muted)]">{evalSet.description}</p>}
          {evalSet && (
            <div className="mt-2 flex items-center gap-2 flex-wrap text-xs text-[var(--color-text-muted)]">
              {evalSet.ref && <span className="ev-badge" title={evalSet.ref}>ref · <span className="font-mono normal-case">{shortHash(evalSet.ref, 10)}</span></span>}
              {evalSet.project_repo && <span className="ev-badge" title="dbt project checked out into each task container">project · <span className="font-mono normal-case">{setNameFromUrl(evalSet.project_repo)}</span></span>}
              {evalSet.build_fingerprint && (
                <span className="ev-badge" title={`build fingerprint ${evalSet.build_fingerprint}`}>
                  build · <span className="font-mono normal-case">{shortHash(evalSet.build_fingerprint)}</span>
                </span>
              )}
            </div>
          )}
          {tasks && (
            <div className="mt-3 flex items-center gap-4 text-xs text-[var(--color-text-muted)] flex-wrap">
              <span><span className="text-[var(--color-text)] text-base">{tasks.length}</span> tasks</span>
              <span className="ev-badge ev-badge--read">read · {tasks.length - writes}</span>
              <span className="ev-badge ev-badge--write">write · {writes}</span>
              {[...kinds.entries()].map(([k, n]) => (
                <span key={k} className="ev-badge">{k} · {n}</span>
              ))}
              <span className="inline-flex items-center gap-1"><BookOpen className="w-3 h-3" /> {documented} documented</span>
              <span>model: <span className="text-[var(--color-text)]">{model}</span></span>
            </div>
          )}
          {!runnerEnabled && (
            <p className="mt-2 text-xs text-[#e5484d]">runner disabled — SP_EVAL_RUNNER_IMAGE unset on gateway</p>
          )}
        </div>
        <div className="flex items-center gap-2">
          <button
            onClick={runAll}
            disabled={!runnerEnabled || !repoUrl || starting}
            title={
              !runnerEnabled
                ? "Runner disabled on the gateway"
                : !repoUrl
                  ? "Configure an eval repo first"
                  : "Grade the whole set against the current knowledge base"
            }
            className="inline-flex items-center gap-2 px-3 py-1.5 rounded-[10px] text-xs border border-[var(--color-border-hover)] text-[var(--color-text)] hover:bg-[var(--color-bg)] disabled:opacity-40 disabled:cursor-not-allowed transition-colors"
          >
            {starting ? <Loader2 className="w-3.5 h-3.5 animate-spin" /> : <Play className="w-3.5 h-3.5" strokeWidth={1.5} />}
            Run all evals
          </button>
          <button onClick={() => setConfigOpen(!configOpen)} className="inline-flex items-center gap-2 px-3 py-1.5 rounded-[10px] text-xs border border-[var(--color-border)] text-[var(--color-text-muted)] hover:border-[var(--color-border-hover)] hover:text-[var(--color-text)] transition-colors">
            <Settings2 className="w-3.5 h-3.5" strokeWidth={1.5} />
            {configOpen ? "Close" : "Configure"}
          </button>
        </div>
      </div>
      {configOpen && <ConfigForm onSaved={() => setConfigOpen(false)} />}
    </div>
  );
}

/* The following code defines the task gallery and detail panel. */

function docTitle(t: EvalTask): string {
  const m = t.doc.match(/^#\s+(.+)$/m);
  return m ? m[1] : t.title;
}

function isControl(t: EvalTask): boolean {
  return t.kind === "control" || /control/i.test(t.why + t.doc.slice(0, 200));
}

function TaskCard({ t, onOpen }: { t: EvalTask; onOpen: () => void }) {
  const rebuild = t.grade?.kind === "model_rebuilt";
  return (
    <button className="ev-qcard" onClick={onOpen}>
      <div className="flex items-start justify-between gap-2">
        <span className="text-sm text-[var(--color-text)] leading-snug">{docTitle(t)}</span>
        <ChevronRight className="w-3.5 h-3.5 mt-0.5 flex-shrink-0 text-[var(--color-text-dim)]" />
      </div>
      <p className="mt-1 text-[11px] font-mono text-[var(--color-text-dim)]">{t.id}</p>
      <div className="mt-3 flex items-center gap-1.5 flex-wrap">
        <ClassBadge cls={t.class} />
        <span className={`ev-badge ${isControl(t) ? "ev-badge--control" : ""}`}>{isControl(t) ? "control" : t.kind}</span>
        {rebuild && <span className="ev-badge">rebuild</span>}
        {t.doc && <span className="ev-badge"><BookOpen className="w-2.5 h-2.5" />docs</span>}
      </div>
      <div className="mt-2.5 flex gap-1.5 flex-wrap">
        {t.checks.map((c) => (
          <span key={c.name} className="ev-chip">
            <span className="n">{c.name}</span>
            {fmtNum(c.value)}
            <span className="n">±{Math.round(c.tolerance * 100)}%</span>
          </span>
        ))}
        {t.builds.length > 0 && (
          <span className="ev-chip"><span className="n">builds</span>{t.builds.length}</span>
        )}
      </div>
    </button>
  );
}

function TaskRow({ t, onOpen }: { t: EvalTask; onOpen: () => void }) {
  return (
    <button className="ev-qrow" onClick={onOpen}>
      <span className="ev-qrow-id">{t.id}</span>
      <span className="ev-qrow-title">{docTitle(t)}</span>
      <span className="ev-qrow-badges">
        <ClassBadge cls={t.class} />
        <span className={`ev-badge ${isControl(t) ? "ev-badge--control" : ""}`}>{isControl(t) ? "control" : t.kind}</span>
        {t.doc && <span className="ev-badge"><BookOpen className="w-2.5 h-2.5" />docs</span>}
      </span>
      <span className="ev-qrow-checks">
        {t.grade?.kind === "model_rebuilt"
          ? "rebuild"
          : t.checks.length
            ? `${t.checks.length} check${t.checks.length === 1 ? "" : "s"}`
            : "ungraded"}
      </span>
      <ChevronRight className="w-3.5 h-3.5 flex-shrink-0 text-[var(--color-text-dim)]" />
    </button>
  );
}

const TASK_PAGE = 60;

function TasksSection({ tasks, onOpen }: { tasks: EvalTask[]; onOpen: (t: EvalTask) => void }) {
  const [query, setQuery] = useState("");
  const [kindFilter, setKindFilter] = useState<string | null>(null);
  const [classFilter, setClassFilter] = useState<string | null>(null);
  // Use the card view for small task sets.
  // Use the list view when the set contains more than 100 tasks.
  // The user can override the default view.
  const [view, setView] = useState<"cards" | "list">(tasks.length > 24 ? "list" : "cards");
  const [limit, setLimit] = useState(TASK_PAGE);

  const kinds = useMemo(() => {
    const m = new Map<string, number>();
    tasks.forEach((t) => m.set(t.kind, (m.get(t.kind) ?? 0) + 1));
    return [...m.entries()].sort((a, b) => b[1] - a[1]);
  }, [tasks]);

  const classes = useMemo(() => {
    const m = new Map<string, number>();
    tasks.forEach((t) => m.set(t.class, (m.get(t.class) ?? 0) + 1));
    return [...m.entries()].sort((a, b) => b[1] - a[1]);
  }, [tasks]);

  const filtered = useMemo(() => {
    const needle = query.trim().toLowerCase();
    return tasks.filter((t) => {
      if (kindFilter && t.kind !== kindFilter) return false;
      if (classFilter && t.class !== classFilter) return false;
      if (!needle) return true;
      return (
        t.id.toLowerCase().includes(needle) ||
        t.title.toLowerCase().includes(needle) ||
        docTitle(t).toLowerCase().includes(needle) ||
        t.prompt.toLowerCase().includes(needle) ||
        t.why.toLowerCase().includes(needle) ||
        t.builds.some((b) => b.toLowerCase().includes(needle)) ||
        t.covers.some((c) => c.toLowerCase().includes(needle))
      );
    });
  }, [tasks, query, kindFilter, classFilter]);

  // Reset paging whenever the visible set changes.
  useEffect(() => setLimit(TASK_PAGE), [query, kindFilter, classFilter, view]);

  const visible = filtered.slice(0, limit);
  const showFilters = tasks.length > 6;

  return (
    <div>
      {showFilters && (
        <div className="ev-toolbar">
          <div className="ev-search">
            <Search className="w-3.5 h-3.5 text-[var(--color-text-dim)]" strokeWidth={1.5} />
            <input
              value={query}
              onChange={(e) => setQuery(e.target.value)}
              placeholder={`Search ${tasks.length} tasks…`}
              aria-label="search tasks"
            />
            {query && (
              <button onClick={() => setQuery("")} aria-label="clear search" className="text-[var(--color-text-dim)] hover:text-[var(--color-text)]">
                <X className="w-3 h-3" />
              </button>
            )}
          </div>
          {classes.length > 1 && (
            <div className="ev-filter-group">
              {classes.map(([c, n]) => (
                <button
                  key={c}
                  className={`ev-filter ${classFilter === c ? "ev-filter--on" : ""}`}
                  onClick={() => setClassFilter(classFilter === c ? null : c)}
                >
                  {c} <span className="n">{n}</span>
                </button>
              ))}
            </div>
          )}
          {kinds.length > 1 && (
            <div className="ev-filter-group">
              {kinds.map(([k, n]) => (
                <button
                  key={k}
                  className={`ev-filter ${kindFilter === k ? "ev-filter--on" : ""}`}
                  onClick={() => setKindFilter(kindFilter === k ? null : k)}
                >
                  {k} <span className="n">{n}</span>
                </button>
              ))}
            </div>
          )}
          <div className="ml-auto flex items-center gap-2">
            <span className="text-[11px] text-[var(--color-text-dim)] tabular-nums whitespace-nowrap">
              {filtered.length === tasks.length ? `${tasks.length}` : `${filtered.length} of ${tasks.length}`}
            </span>
            <div className="ev-view-toggle" role="group" aria-label="view mode">
              <button className={view === "list" ? "on" : ""} onClick={() => setView("list")} title="List view" aria-label="list view">
                <List className="w-3.5 h-3.5" strokeWidth={1.5} />
              </button>
              <button className={view === "cards" ? "on" : ""} onClick={() => setView("cards")} title="Card view" aria-label="card view">
                <LayoutGrid className="w-3.5 h-3.5" strokeWidth={1.5} />
              </button>
            </div>
          </div>
        </div>
      )}

      {filtered.length === 0 ? (
        <p className="mt-4 text-sm text-[var(--color-text-dim)]">no tasks match — clear the search or filters</p>
      ) : view === "cards" ? (
        <div className="mt-3 grid grid-cols-1 md:grid-cols-2 xl:grid-cols-3 2xl:grid-cols-4 gap-3">
          {visible.map((t) => (
            <TaskCard key={t.id} t={t} onOpen={() => onOpen(t)} />
          ))}
        </div>
      ) : (
        <div className="mt-3 ev-card divide-y divide-[var(--color-border)]">
          {visible.map((t) => (
            <TaskRow key={t.id} t={t} onOpen={() => onOpen(t)} />
          ))}
        </div>
      )}

      {filtered.length > limit && (
        <div className="mt-3 flex justify-center">
          <button
            onClick={() => setLimit(limit + TASK_PAGE)}
            className="px-4 py-1.5 rounded-[10px] text-xs border border-[var(--color-border)] text-[var(--color-text-muted)] hover:border-[var(--color-border-hover)] hover:text-[var(--color-text)] transition-colors"
          >
            Show {Math.min(TASK_PAGE, filtered.length - limit)} more · {filtered.length - limit} remaining
          </button>
        </div>
      )}
    </div>
  );
}

/** The grading specification contains numeric checks or model_rebuilt expectations. */
function GradeSpec({ grade, checks }: { grade: EvalGrade | null; checks: EvalTask["checks"] }) {
  const rebuilt = grade?.kind === "model_rebuilt";
  const expectations = rebuilt && Array.isArray(grade?.expectations) ? grade.expectations : null;
  return (
    <div>
      <h3 className="text-[11px] uppercase tracking-[0.08em] text-[var(--color-text-dim)] mb-2">
        Grading{rebuilt ? " — model rebuilt" : " — gold checks"}
      </h3>
      {rebuilt && (
        <p className="text-xs text-[var(--color-text-muted)] mb-2">
          The agent must rebuild the model on its branch; grading verifies the rebuilt model
          against these expectations.
        </p>
      )}
      <table className="w-full text-left border-collapse text-sm">
        <thead>
          <tr className="text-[10px] uppercase tracking-wider text-[var(--color-text-dim)]">
            <th className="py-1 pr-4 font-normal">{rebuilt ? "expectation" : "check"}</th>
            <th className="py-1 pr-4 font-normal">gold value</th>
            <th className="py-1 font-normal">tolerance</th>
          </tr>
        </thead>
        <tbody>
          {(expectations ?? checks).length ? (
            (expectations ?? checks).map((c) => (
              <tr key={c.name} className="border-t border-[var(--color-border)]">
                <td className="py-1.5 pr-4 font-mono text-xs text-[var(--color-text-muted)]">{c.name}</td>
                <td className="py-1.5 pr-4 font-mono text-xs text-[var(--color-text)]">{c.value != null ? c.value.toLocaleString() : "—"}</td>
                <td className="py-1.5 font-mono text-xs text-[var(--color-text-muted)]">{c.tolerance != null ? `±${Math.round(c.tolerance * 100)}%` : "—"}</td>
              </tr>
            ))
          ) : (
            <tr className="border-t border-[var(--color-border)]">
              <td colSpan={3} className="py-1.5 text-xs text-[var(--color-text-dim)]">
                {rebuilt ? "graded on the model rebuild itself" : "ungraded — no numeric gold"}
              </td>
            </tr>
          )}
        </tbody>
      </table>
    </div>
  );
}

function ChipList({ label, items }: { label: string; items: string[] }) {
  if (!items?.length) return null;
  return (
    <div>
      <h3 className="text-[11px] uppercase tracking-[0.08em] text-[var(--color-text-dim)] mb-2">{label}</h3>
      <div className="flex gap-1.5 flex-wrap">
        {items.map((m) => (
          <span key={m} className="ev-chip"><span className="font-mono">{m}</span></span>
        ))}
      </div>
    </div>
  );
}

function TaskDetail({ t, onClose }: { t: EvalTask; onClose: () => void }) {
  // The animate-fade-in class leaves a transform on the page shell.
  // Render the panel in document.body to use the viewport as its containing block.
  const [portalTarget, setPortalTarget] = useState<HTMLElement | null>(null);
  useEffect(() => setPortalTarget(document.body), []);

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => e.key === "Escape" && onClose();
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [onClose]);

  if (!portalTarget) return null;

  return createPortal(
    <>
      <div className="ev-overlay" onClick={onClose} />
      <div className="ev-panel">
        <div className="sticky top-0 bg-[var(--color-bg-card)] border-b border-[var(--color-border)] px-6 py-4 flex items-center justify-between">
          <div>
            <code className="text-xs text-[var(--color-text-dim)]">{t.id}</code>
            <div className="flex items-center gap-1.5 mt-1">
              <ClassBadge cls={t.class} />
              <span className="ev-badge">{t.kind}</span>
              {t.grade?.kind === "model_rebuilt" && <span className="ev-badge">rebuild</span>}
            </div>
          </div>
          <button onClick={onClose} aria-label="close" className="text-[var(--color-text-dim)] hover:text-[var(--color-text)]">
            <X className="w-4 h-4" />
          </button>
        </div>
        <div className="px-6 py-5 space-y-6">
          {t.doc ? (
            <Md>{t.doc}</Md>
          ) : (
            <p className="text-sm text-[var(--color-text-dim)]">
              No writeup — add <code>docs/{t.id}.md</code> to the eval repo (see eval-format.md).
            </p>
          )}

          <div>
            <h3 className="text-[11px] uppercase tracking-[0.08em] text-[var(--color-text-dim)] mb-2">Prompt sent to the agent</h3>
            <pre className="ev-raw border border-[var(--color-border)] rounded-[10px] bg-[var(--color-bg)] p-3">{t.prompt}</pre>
          </div>

          <GradeSpec grade={t.grade} checks={t.checks} />

          <ChipList label="Covers — models this task exercises" items={t.covers} />
          <ChipList label="Builds — models the agent must build" items={t.builds} />

          {t.capture && (
            <div>
              <h3 className="text-[11px] uppercase tracking-[0.08em] text-[var(--color-text-dim)] mb-2">Capture</h3>
              <div className="flex items-center gap-1.5 flex-wrap text-xs text-[var(--color-text-muted)]">
                {t.capture.tables.map((tb) => (
                  <span key={tb} className="ev-chip"><span className="font-mono">{tb}</span></span>
                ))}
                <span className="ev-badge">mode · {t.capture.mode}</span>
                <span className="ev-badge">{t.capture.sample_rows} sample rows</span>
              </div>
            </div>
          )}

          {(t.setup || t.teardown) && (
            <div>
              <h3 className="text-[11px] uppercase tracking-[0.08em] text-[var(--color-text-dim)] mb-2">Setup / teardown</h3>
              <div className="space-y-1 text-xs font-mono text-[var(--color-text-muted)]">
                {t.setup && <p><span className="text-[var(--color-text-dim)]">setup ·</span> {t.setup}</p>}
                {t.teardown && <p><span className="text-[var(--color-text-dim)]">teardown ·</span> {t.teardown}</p>}
              </div>
            </div>
          )}
        </div>
      </div>
    </>,
    portalTarget,
  );
}

/* The following code displays evaluation runs. */

/** This control displays the setup or teardown log for a write task. */
function TaskPhaseLog({ runId, taskId, phase }: { runId: string; taskId: string; phase: "setup" | "teardown" }) {
  const [log, setLog] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);
  async function toggle(e: React.MouseEvent) {
    e.stopPropagation();
    if (log !== null) return setLog(null);
    setLoading(true);
    try {
      setLog(await getEvalSetupLog(runId, taskId, phase));
    } catch {
      setLog(`(${phase} log not available)`);
    } finally {
      setLoading(false);
    }
  }
  return (
    <div className="inline-block align-top">
      <button
        onClick={toggle}
        className="text-xs text-[var(--color-text-muted)] hover:text-[var(--color-text)] underline underline-offset-2 inline-flex items-center gap-1"
      >
        {loading && <Loader2 className="w-3 h-3 animate-spin" />}
        {log !== null ? `hide ${phase} log` : `${phase} log`}
      </button>
      {log !== null && (
        <pre className="ev-raw mt-2 border border-[var(--color-border)] rounded-[10px] bg-[var(--color-bg)] p-3">{log.slice(-20000)}</pre>
      )}
    </div>
  );
}

function CaptureSummary({ task, runId }: { task: EvalRunTask; runId: string }) {
  const { toast } = useToast();
  const cr = task.capture_result;
  if (!cr) return null;
  const stored = Array.isArray(cr.stored) ? cr.stored : [];
  return (
    <div className="mt-2 flex items-center gap-2 flex-wrap text-xs text-[var(--color-text-muted)]">
      <span className="text-[10px] uppercase tracking-[0.14em] text-[var(--color-text-dim)]">capture</span>
      {cr.row_count != null && <span className="font-mono tabular-nums">{cr.row_count.toLocaleString()} rows</span>}
      {cr.grain_unique != null && (
        <span style={{ color: cr.grain_unique ? "var(--color-success)" : "#e5484d" }}>
          grain {cr.grain_unique ? "unique" : "not unique"}
        </span>
      )}
      {stored.map((f) => {
        const filename = f.split("/").pop() || f;
        return (
          <button
            key={f}
            onClick={(e) => {
              e.stopPropagation();
              downloadEvalArtifact(runId, task.id, filename).catch(() =>
                toast(`could not download ${filename}`, "error"),
              );
            }}
            className="ev-chip hover:border-[var(--color-border-hover)]"
            title={`download ${f}`}
          >
            <Download className="w-2.5 h-2.5" />
            <span className="font-mono">{filename}</span>
          </button>
        );
      })}
    </div>
  );
}

function RunTaskRow({ task, runId }: { task: EvalRunTask; runId: string }) {
  const [open, setOpen] = useState(false);
  const [showTranscript, setShowTranscript] = useState(false);
  const isWrite = task.task_class === "write";
  return (
    <>
      <tr className="border-t border-[var(--color-border)] cursor-pointer hover:bg-[var(--color-bg)]" onClick={() => setOpen(!open)}>
        <td className="py-2.5 pr-2 text-[var(--color-text-dim)]">
          {open ? <ChevronDown className="w-3.5 h-3.5" /> : <ChevronRight className="w-3.5 h-3.5" />}
        </td>
        <td className="py-2.5 pr-4 text-sm text-[var(--color-text)]">{task.title}</td>
        <td className="py-2.5 pr-4"><ClassBadge cls={task.task_class} /></td>
        <td className="py-2.5 pr-4">
          {task.status === "running" ? (
            <span className="inline-flex items-center gap-1.5 text-xs text-[var(--color-warning,#f5a623)]">
              <Loader2 className="w-3 h-3 animate-spin" /> running
            </span>
          ) : task.status === "pending" ? (
            <span className="text-xs text-[var(--color-text-dim)]">queued</span>
          ) : (
            <VerdictBadge verdict={task.verdict} />
          )}
        </td>
        <td className="py-2.5 pr-4"><CheckChips results={task.check_results ?? []} /></td>
        <td className="py-2.5 text-xs text-[var(--color-text-dim)] font-mono tabular-nums whitespace-nowrap">{task.duration_s ? `${task.duration_s}s` : ""}</td>
      </tr>
      {open && (
        <tr className="border-t border-[var(--color-border)]">
          <td />
          <td colSpan={5} className="py-3 pr-4">
            {task.error && <p className="mb-2 text-xs text-[#e5484d]">{task.error}</p>}
            {isWrite && task.branch_name && (
              <p className="mb-2 text-xs text-[var(--color-text-muted)] inline-flex items-center gap-1.5">
                <GitBranch className="w-3 h-3 text-[var(--color-text-dim)]" strokeWidth={1.5} />
                <code className="text-[var(--color-text)]">{task.branch_name}</code>
              </p>
            )}
            <div className="text-[10px] uppercase tracking-[0.14em] text-[var(--color-text-dim)] mb-1.5">final answer</div>
            <div className="border border-[var(--color-border)] rounded-[10px] bg-[var(--color-bg)] px-4 py-3 max-h-72 overflow-y-auto">
              <Md>{task.answer || "*(no answer captured yet)*"}</Md>
            </div>
            <CaptureSummary task={task} runId={runId} />
            <div className="mt-2 flex items-start gap-4 flex-wrap">
              <button
                onClick={(e) => { e.stopPropagation(); setShowTranscript(true); }}
                className="text-xs text-[var(--color-text-muted)] hover:text-[var(--color-text)] underline underline-offset-2"
              >
                view full transcript
              </button>
              {isWrite && (
                <>
                  <TaskPhaseLog runId={runId} taskId={task.id} phase="setup" />
                  <TaskPhaseLog runId={runId} taskId={task.id} phase="teardown" />
                </>
              )}
            </div>
            {showTranscript && (
              <TranscriptSlideOver
                runId={runId}
                taskId={task.id}
                title={task.title}
                onClose={() => setShowTranscript(false)}
              />
            )}
          </td>
        </tr>
      )}
    </>
  );
}

/* The following code defines the coverage panel. */

function layerPct(l: EvalCoverageLayer): number | null {
  if (l.pct != null) return l.pct;
  if (l.total && l.covered != null) return (l.covered / l.total) * 100;
  return null;
}

const NOT_DECLARED_CAP = 24;

function CoveragePanel({ coverage }: { coverage: EvalCoverage }) {
  const layers = Object.entries(coverage.by_layer ?? {});
  const extra = coverage.observed_not_declared ?? [];
  return (
    <div className="mt-4 border border-[var(--color-border)] rounded-[10px] bg-[var(--color-bg)] px-4 py-3">
      <div className="flex items-center gap-4 flex-wrap text-xs text-[var(--color-text-muted)]">
        <span className="text-[10px] uppercase tracking-[0.14em] text-[var(--color-text-dim)]">model coverage</span>
        {coverage.pct != null && (
          <span><span className="text-[var(--color-text)] text-base tabular-nums">{coverage.pct.toFixed(0)}%</span> overall</span>
        )}
        {coverage.marts_pct != null && (
          <span><span className="text-[var(--color-text)] tabular-nums">{coverage.marts_pct.toFixed(0)}%</span> marts</span>
        )}
        {coverage.models_total != null && (
          <span className="font-mono tabular-nums text-[var(--color-text-dim)]">
            {coverage.models_covered ?? coverage.observed.length}/{coverage.models_total} models
          </span>
        )}
      </div>
      {layers.length > 0 && (
        <div className="mt-3 grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-x-6 gap-y-2">
          {layers.map(([name, l]) => {
            const pct = layerPct(l);
            return (
              <div key={name}>
                <div className="flex items-baseline justify-between text-[11px] mb-1">
                  <span className="font-mono text-[var(--color-text-muted)]">{name}</span>
                  <span className="tabular-nums text-[var(--color-text-dim)]">
                    {l.covered != null && l.total != null ? `${l.covered}/${l.total}` : pct != null ? `${pct.toFixed(0)}%` : "—"}
                  </span>
                </div>
                <div className="ev-cov-bar">
                  <div style={{ width: `${Math.min(100, Math.max(0, pct ?? 0))}%` }} />
                </div>
              </div>
            );
          })}
        </div>
      )}
      {extra.length > 0 && (
        <div className="mt-3">
          <div className="text-[10px] uppercase tracking-[0.14em] text-[var(--color-text-dim)] mb-1.5">
            observed but not declared — tables the agents touched outside the set’s covers
          </div>
          <div className="flex gap-1.5 flex-wrap">
            {extra.slice(0, NOT_DECLARED_CAP).map((m) => (
              <span key={m} className="ev-chip"><span className="font-mono">{m}</span></span>
            ))}
            {extra.length > NOT_DECLARED_CAP && (
              <span className="text-[11px] text-[var(--color-text-dim)] self-center">+{extra.length - NOT_DECLARED_CAP} more</span>
            )}
          </div>
        </div>
      )}
    </div>
  );
}

/* The following code defines the run details. */

function RunDetail({ runId }: { runId: string }) {
  const { toast } = useToast();
  const [exporting, setExporting] = useState(false);
  const [stopping, setStopping] = useState(false);
  const { data: run } = useSWR(`eval-run-${runId}`, () => getEvalRun(runId), {
    refreshInterval: (latest) => (latest && (latest.status === "running" || latest.status === "preparing" || latest.status === "cancelling") ? 2000 : 0),
  });
  const live = run?.status === "running" || run?.status === "preparing" || run?.status === "cancelling";
  const { data: progress } = useSWR(
    live ? `eval-run-progress-${runId}` : null,
    () => getEvalRunProgress(runId),
    { refreshInterval: 2000 },
  );
  if (!run) return <div className="ev-card p-5 text-sm text-[var(--color-text-dim)]">loading run…</div>;

  async function exportZip() {
    setExporting(true);
    try {
      await downloadEvalRunExport(runId);
    } catch (err) {
      toast(`export failed: ${err instanceof Error ? err.message : "unknown"}`, "error");
    } finally {
      setExporting(false);
    }
  }

  async function stopRun() {
    setStopping(true);
    try {
      await cancelEvalRun(runId);
      await Promise.all([mutate("eval-runs"), mutate(`eval-run-${runId}`)]);
      toast("eval cancellation requested", "success");
    } catch (err) {
      toast(`could not stop run: ${err instanceof Error ? err.message : "unknown"}`, "error");
    } finally {
      setStopping(false);
    }
  }

  const s = run.summary ?? {};
  const allPass = (s.correct ?? 0) === (s.total ?? 0) && (s.total ?? 0) > 0;
  return (
    <div className="ev-card p-5">
      <div className="flex items-center justify-between flex-wrap gap-2">
        <div>
          <div className="flex items-center gap-3 flex-wrap">
            <code className="text-sm text-[var(--color-text)]">{run.id}</code>
            <StatusDot status={run.status} />
            {run.trigger && <span className="ev-badge">{run.trigger}</span>}
          </div>
          <p className="mt-1 text-xs text-[var(--color-text-muted)]">
            {run.doc_titles.length > 0 ? (
              <>
                Testing proposed {run.doc_titles.length === 1 ? "entry" : "entries"}:{" "}
                <span className="text-[var(--color-text)]">{run.doc_titles.join(", ")}</span>
              </>
            ) : (
              <>Whole-set run against the live knowledge base</>
            )}
            {" · "}model {run.model}
          </p>
          <p className="mt-1 text-[11px] text-[var(--color-text-dim)] font-mono">
            {run.eval_set_name}
            {run.eval_set_ref ? `@${shortHash(run.eval_set_ref, 10)}` : ""}
            {run.build_fingerprint ? ` · build ${shortHash(run.build_fingerprint)}` : ""}
            {run.artifacts_pruned || run.traces_pruned ? " · artifacts pruned" : ""}
          </p>
        </div>
        <div className="flex items-center gap-3 flex-wrap">
          {live && (
            <button
              onClick={stopRun}
              disabled={stopping || run.status === "cancelling"}
              className="ev-stop-command"
            >
              {stopping || run.status === "cancelling" ? <Loader2 className="w-3.5 h-3.5 animate-spin" /> : <Square className="w-3 h-3" fill="currentColor" />}
              {run.status === "cancelling" ? "Stopping" : "Stop run"}
            </button>
          )}
          {run.status === "completed" && (
            <div className="flex items-center gap-3 text-sm">
              {allPass ? <CheckCircle2 className="w-4 h-4 text-[var(--color-success)]" /> : <XCircle className="w-4 h-4 text-[#e5484d]" />}
              <span className="text-[var(--color-text)]">{s.correct ?? 0}/{s.total ?? 0} correct</span>
              {(s.partial ?? 0) > 0 && <span className="text-xs text-[var(--color-warning,#f5a623)]">{s.partial} partial</span>}
              {(s.error ?? 0) > 0 && <span className="text-xs text-[#e5484d]">{s.error} error</span>}
              {(s.setup_failed ?? 0) > 0 && <span className="text-xs text-[#e5484d]">{s.setup_failed} setup failed</span>}
            </div>
          )}
          {!live && (
            <button
              onClick={exportZip}
              disabled={exporting}
              title="Download the full run archive — transcripts, artifacts, result JSON"
              className="inline-flex items-center gap-2 px-3 py-1.5 rounded-[10px] text-xs border border-[var(--color-border)] text-[var(--color-text-muted)] hover:border-[var(--color-border-hover)] hover:text-[var(--color-text)] disabled:opacity-40 transition-colors"
            >
              {exporting ? <Loader2 className="w-3.5 h-3.5 animate-spin" /> : <Download className="w-3.5 h-3.5" strokeWidth={1.5} />}
              Export zip
            </button>
          )}
        </div>
      </div>

      {run.error && <p className="mt-3 text-sm text-[#e5484d]">{run.error}</p>}

      {progress && <RunProgressBar progress={progress} />}

      {run.tasks.length > 0 && (
        <table className="mt-4 w-full text-left border-collapse">
          <thead>
            <tr className="text-[10px] uppercase tracking-wider text-[var(--color-text-dim)]">
              <th className="w-6" />
              <th className="py-1 pr-4 font-normal">task</th>
              <th className="py-1 pr-4 font-normal">class</th>
              <th className="py-1 pr-4 font-normal">verdict</th>
              <th className="py-1 pr-4 font-normal">checks</th>
              <th className="py-1 font-normal">time</th>
            </tr>
          </thead>
          <tbody>
            {[...run.tasks]
              .sort((a, b) => (a.position ?? 0) - (b.position ?? 0))
              .map((t) => (
                <RunTaskRow key={t.id} task={t} runId={run.id} />
              ))}
          </tbody>
        </table>
      )}

      {run.coverage && <CoveragePanel coverage={run.coverage} />}
    </div>
  );
}

/* The following code defines accuracy history and regressions. */

const TRIGGER_COLOR: Record<string, string> = {
  manual: "var(--color-success)",
  knowledge_add: "#6e9fd6",
  schedule: "#c678aa",
};

type AccuracyChartPoint = {
  run_id: string;
  label: string;
  accuracy: number;
  coverage: number | null;
  trigger: string;
  tasks_passed: number;
  tasks_total: number;
  regressed: boolean;
};

type DotProps = { cx?: number; cy?: number; payload?: AccuracyChartPoint };

function AccuracyDot({ cx, cy, payload }: DotProps) {
  if (cx == null || cy == null || !payload) return <circle cx={0} cy={0} r={0} opacity={0} />;
  const color = payload.regressed
    ? "#e5484d"
    : TRIGGER_COLOR[payload.trigger] ?? "var(--color-text-dim)";
  return (
    <circle
      cx={cx}
      cy={cy}
      r={payload.regressed ? 4.5 : 3}
      fill={color}
      stroke={payload.regressed ? "#e5484d" : "none"}
      strokeWidth={payload.regressed ? 1.5 : 0}
      fillOpacity={payload.regressed ? 0.35 : 1}
    />
  );
}

function AccuracyTooltip({
  active,
  payload,
}: {
  active?: boolean;
  payload?: Array<{ payload: AccuracyChartPoint }>;
}) {
  if (!active || !payload?.length) return null;
  const p = payload[0].payload;
  return (
    <div className="bg-[var(--color-bg-card)] border border-[var(--color-border)] rounded-[10px] px-3 py-2 text-xs">
      <p className="font-mono text-[11px] text-[var(--color-text-dim)] mb-0.5">{p.run_id}</p>
      <p className="text-[var(--color-text)] tabular-nums">
        {p.accuracy.toFixed(1)}% · {p.tasks_passed}/{p.tasks_total} passed
      </p>
      <p className="text-[var(--color-text-dim)]">
        {p.trigger}
        {p.coverage != null && ` · coverage ${p.coverage.toFixed(0)}%`}
        {p.regressed && " · regression"}
      </p>
    </div>
  );
}

function AccuracySection() {
  const { data } = useSWR("eval-accuracy", getEvalAccuracy, { refreshInterval: 30000 });
  const history = useMemo(() => data?.history ?? [], [data]);
  const regressions = useMemo(() => data?.regressions ?? [], [data]);

  const points = useMemo<AccuracyChartPoint[]>(() => {
    const regressed = new Set(regressions.map((r) => r.run_id));
    return [...history]
      .sort((a, b) => a.created_at.localeCompare(b.created_at))
      .map((h) => ({
        run_id: h.run_id,
        label: new Date(h.created_at).toLocaleDateString("en-US", { month: "short", day: "numeric" }),
        accuracy: h.accuracy_pct,
        coverage: h.coverage_pct,
        trigger: h.trigger,
        tasks_passed: h.tasks_passed,
        tasks_total: h.tasks_total,
        regressed: regressed.has(h.run_id),
      }));
  }, [history, regressions]);

  const hasCoverage = points.some((p) => p.coverage != null);

  return (
    <div className="ev-card p-5">
      <div className="flex items-center gap-3 flex-wrap mb-3">
        <h2 className="text-[11px] uppercase tracking-[0.08em] text-[var(--color-text-muted)] inline-flex items-center gap-2">
          <TrendingUp className="w-3.5 h-3.5" strokeWidth={1.5} /> Accuracy over time
        </h2>
        {points.length >= 2 && (
          <div className="ml-auto flex items-center gap-3 text-[11px] text-[var(--color-text-dim)]">
            <span className="inline-flex items-center gap-1.5"><span className="w-1.5 h-1.5 rounded-full" style={{ background: TRIGGER_COLOR.manual }} /> manual</span>
            <span className="inline-flex items-center gap-1.5"><span className="w-1.5 h-1.5 rounded-full" style={{ background: TRIGGER_COLOR.knowledge_add }} /> knowledge add</span>
            <span className="inline-flex items-center gap-1.5"><span className="w-1.5 h-1.5 rounded-full" style={{ background: "#e5484d" }} /> regression</span>
            {hasCoverage && (
              <span className="inline-flex items-center gap-1.5"><span className="w-4 border-t border-dashed" style={{ borderColor: "#6e9fd6" }} /> coverage</span>
            )}
          </div>
        )}
      </div>

      {points.length < 2 ? (
        <p className="text-sm text-[var(--color-text-dim)]">
          Not enough history yet — the accuracy trend appears after two completed runs.
        </p>
      ) : (
        <ResponsiveContainer width="100%" height={200}>
          <LineChart data={points} margin={{ top: 4, right: 4, bottom: 0, left: 0 }}>
            <CartesianGrid stroke="var(--color-border)" strokeDasharray="3 3" vertical={false} />
            <XAxis
              dataKey="label"
              tick={{ fontSize: 10, fill: "var(--color-text-dim)", fontFamily: "monospace" }}
              tickLine={false}
              axisLine={false}
              interval="preserveStartEnd"
            />
            <YAxis
              domain={[0, 100]}
              tick={{ fontSize: 10, fill: "var(--color-text-dim)", fontFamily: "monospace" }}
              tickLine={false}
              axisLine={false}
              width={36}
            />
            <Tooltip content={<AccuracyTooltip />} cursor={{ stroke: "var(--color-border-hover)" }} />
            {hasCoverage && (
              <Line
                type="monotone"
                dataKey="coverage"
                stroke="#6e9fd6"
                strokeWidth={1}
                strokeDasharray="4 3"
                dot={false}
                connectNulls
                isAnimationActive={false}
              />
            )}
            <Line
              type="monotone"
              dataKey="accuracy"
              stroke="var(--color-success)"
              strokeWidth={1.5}
              dot={(props: DotProps) => <AccuracyDot {...props} />}
              isAnimationActive={false}
            />
          </LineChart>
        </ResponsiveContainer>
      )}

      {regressions.length > 0 && (
        <div className="mt-4 pt-3 border-t border-[var(--color-border)]">
          <div className="text-[10px] uppercase tracking-[0.14em] text-[var(--color-text-dim)] mb-1.5">regressions</div>
          <div className="space-y-1.5">
            {[...regressions]
              .sort((a, b) => b.created_at.localeCompare(a.created_at))
              .map((r) => (
                <div key={r.id} className="flex items-baseline gap-2 flex-wrap text-xs">
                  <span className="w-1.5 h-1.5 rounded-full flex-shrink-0 self-center" style={{ background: "#e5484d" }} />
                  <code className="text-[var(--color-text)]">{r.run_id}</code>
                  <span className="text-[var(--color-text)]">
                    dropped {r.baseline_accuracy_pct.toFixed(1)}→{r.run_accuracy_pct.toFixed(1)} pts
                    <span className="text-[#e5484d]"> (−{r.drop_pct.toFixed(1)})</span>
                  </span>
                  {r.sole_change && r.suspected_doc_ids.length > 0 ? (
                    <span className="text-[var(--color-text-muted)]">
                      caused by <code className="text-[var(--color-text)]">{r.suspected_doc_ids[0]}</code>
                    </span>
                  ) : r.suspected_doc_ids.length > 0 ? (
                    <span className="text-[var(--color-text-muted)]">
                      coincided with {r.suspected_doc_ids.length} knowledge {r.suspected_doc_ids.length === 1 ? "entry" : "entries"}
                    </span>
                  ) : null}
                  {r.flipped_tasks.length > 0 && (
                    <span className="text-[var(--color-text-dim)]">{r.flipped_tasks.length} task{r.flipped_tasks.length === 1 ? "" : "s"} flipped</span>
                  )}
                  <span className="ml-auto text-[var(--color-text-dim)] font-mono tabular-nums whitespace-nowrap">
                    {new Date(r.created_at).toLocaleDateString("en-US", { month: "short", day: "numeric" })}
                  </span>
                </div>
              ))}
          </div>
        </div>
      )}
    </div>
  );
}

/* The following code defines the run list. */

const RUNS_COLLAPSED = 8;

function RunsList({ runs, selectedRun, onSelect }: { runs: EvalRun[]; selectedRun: string | null; onSelect: (id: string) => void }) {
  const [query, setQuery] = useState("");
  const [showAll, setShowAll] = useState(false);

  const filtered = useMemo(() => {
    const needle = query.trim().toLowerCase();
    if (!needle) return runs;
    return runs.filter(
      (r) =>
        r.id.toLowerCase().includes(needle) ||
        r.doc_titles.some((t) => t.toLowerCase().includes(needle)) ||
        r.doc_ids.some((t) => t.toLowerCase().includes(needle)) ||
        (r.trigger ?? "").includes(needle) ||
        r.status.includes(needle),
    );
  }, [runs, query]);

  const visible = showAll || query ? filtered : filtered.slice(0, RUNS_COLLAPSED);
  const hidden = filtered.length - visible.length;

  return (
    <div className="ev-card p-5">
      <div className="flex items-center justify-between gap-3 mb-3">
        <h2 className="text-[11px] uppercase tracking-[0.08em] text-[var(--color-text-muted)]">
          Runs{runs.length > 0 && <span className="ml-1.5 normal-case tracking-normal text-[var(--color-text-dim)]">{runs.length}</span>}
        </h2>
        {runs.length > RUNS_COLLAPSED && (
          <div className="ev-search ev-search--sm">
            <Search className="w-3 h-3 text-[var(--color-text-dim)]" strokeWidth={1.5} />
            <input value={query} onChange={(e) => setQuery(e.target.value)} placeholder="Filter runs…" aria-label="filter runs" />
            {query && (
              <button onClick={() => setQuery("")} aria-label="clear filter" className="text-[var(--color-text-dim)] hover:text-[var(--color-text)]">
                <X className="w-3 h-3" />
              </button>
            )}
          </div>
        )}
      </div>
      {runs.length === 0 ? (
        <p className="text-sm text-[var(--color-text-dim)] flex items-center gap-2">
          <FlaskConical className="w-4 h-4" strokeWidth={1.5} />
          No runs yet — open a pending knowledge entry and click “Evaluate Change”.
        </p>
      ) : filtered.length === 0 ? (
        <p className="text-sm text-[var(--color-text-dim)]">no runs match “{query}”</p>
      ) : (
        <>
          <div className="divide-y divide-[var(--color-border)]">
            {visible.map((r) => {
              const s = r.summary ?? {};
              return (
                <button
                  key={r.id}
                  onClick={() => onSelect(r.id)}
                  className={`w-full flex items-center justify-between py-2.5 px-2 rounded-[10px] text-left hover:bg-[var(--color-bg)] transition-colors duration-150 ${selectedRun === r.id ? "bg-[var(--color-bg)]" : ""}`}
                >
                  <div className="min-w-0 flex items-baseline gap-3">
                    <code className="text-sm text-[var(--color-text)] whitespace-nowrap">{r.id}</code>
                    {r.trigger && <span className="ev-badge flex-shrink-0">{r.trigger}</span>}
                    <p className="text-xs text-[var(--color-text-muted)] truncate">
                      {r.doc_titles.join(", ") || r.doc_ids.join(", ") || "whole set"}
                    </p>
                  </div>
                  <div className="flex items-center gap-4 flex-shrink-0 ml-4">
                    {r.status === "completed" && (
                      <span className="text-xs text-[var(--color-text-muted)] tabular-nums">{s.correct ?? 0}/{s.total ?? 0} correct</span>
                    )}
                    <StatusDot status={r.status} />
                  </div>
                </button>
              );
            })}
          </div>
          {hidden > 0 && (
            <button
              onClick={() => setShowAll(true)}
              className="mt-2 w-full py-1.5 text-xs text-[var(--color-text-dim)] hover:text-[var(--color-text)] transition-colors"
            >
              Show all {filtered.length} runs
            </button>
          )}
          {showAll && !query && filtered.length > RUNS_COLLAPSED && (
            <button
              onClick={() => setShowAll(false)}
              className="mt-2 w-full py-1.5 text-xs text-[var(--color-text-dim)] hover:text-[var(--color-text)] transition-colors"
            >
              Show recent only
            </button>
          )}
        </>
      )}
    </div>
  );
}

/* The following code displays unavailable evaluation settings. */

function SetupState() {
  return (
    <div className="ev-card p-8">
      <div className="flex items-center gap-3">
        <FlaskConical className="w-5 h-5 text-[var(--color-text-dim)]" strokeWidth={1.25} />
        <h2 className="text-2xl font-semibold tracking-[-0.01em] text-[var(--color-text)]">
          Evals aren’t set up for this workspace
        </h2>
      </div>
      <p className="mt-3 text-sm text-[var(--color-text-muted)] max-w-2xl leading-relaxed">
        Evals run your proposed knowledge entries against a graded task set, so you can see
        whether an entry actually changes an agent’s answers before you approve it. It’s enabled
        per workspace during onboarding.
      </p>

      <div className="mt-6 pt-5 border-t border-[var(--color-border)]">
        <h3 className="text-[11px] uppercase tracking-[0.08em] text-[var(--color-text-dim)] mb-3">
          How to get access
        </h3>
        <ol className="space-y-2.5 text-sm text-[var(--color-text-muted)] max-w-2xl">
          <li className="flex gap-3">
            <span className="ev-badge flex-shrink-0">1</span>
            <span>
              Email{" "}
              <a
                href="mailto:support@signalpilot.dev?subject=Enable%20evals%20for%20my%20workspace"
                className="text-[var(--color-text)] underline underline-offset-2"
              >
                support@signalpilot.dev
              </a>{" "}
              from the workspace you want enabled.
            </span>
          </li>
          <li className="flex gap-3">
            <span className="ev-badge flex-shrink-0">2</span>
            <span>We turn evals on for that workspace and connect your eval set.</span>
          </li>
          <li className="flex gap-3">
            <span className="ev-badge flex-shrink-0">3</span>
            <span>
              “Evaluate Change” then appears on pending knowledge entries, and runs show up here.
            </span>
          </li>
        </ol>
        <p className="mt-5 text-xs text-[var(--color-text-dim)]">
          Already enabled elsewhere? Evals follow the active organization — switch to it from the
          workspace switcher.
        </p>
      </div>
    </div>
  );
}

/* The following code defines the evaluation page. */

function EvalsPageInner() {
  const searchParams = useSearchParams();
  const [selectedRun, setSelectedRun] = useState<string | null>(() => searchParams.get("run"));
  const [detailTask, setDetailTask] = useState<EvalTask | null>(null);
  const [configOpen, setConfigOpen] = useState(false);

  // An unentitled workspace can call only the availability route.
  // Delay all other requests until the availability response confirms access.
  const { data: availability, isLoading: availLoading } = useSWR("eval-availability", getEvalAvailability);
  const enabled = availability?.enabled === true;

  const { data: cfg, isLoading: cfgLoading } = useSWR(enabled ? "eval-config" : null, getEvalConfig);
  const { data: evalSet, error: tasksError } = useSWR(
    enabled && cfg?.repo_url ? `eval-tasks-${cfg.repo_url}` : null,
    () => listEvalTasks(),
  );
  const tasks = evalSet?.tasks;
  const { data: runsData } = useSWR(enabled ? "eval-runs" : null, listEvalRuns, {
    refreshInterval: (latest) =>
      latest?.runs?.some((r: EvalRun) => r.status === "running" || r.status === "preparing" || r.status === "cancelling") ? 2500 : 15000,
  });
  const runs = runsData?.runs ?? [];
  const activeRun = runs.find((run) => run.status === "running" || run.status === "preparing" || run.status === "cancelling");

  const header = (
    <PageHeader
      title="evals"
      subtitle="knowledge"
      description="test proposed knowledge entries against your eval suite before approving"
    />
  );

  if (!enabled) {
    return (
      <div className="min-h-screen p-8 animate-fade-in">
        {header}
        <div className="max-w-5xl">
          {availLoading || !availability ? (
            <div className="ev-card p-8 text-sm text-[var(--color-text-dim)] flex items-center gap-2">
              <Loader2 className="w-4 h-4 animate-spin" /> loading…
            </div>
          ) : (
            <SetupState />
          )}
        </div>
      </div>
    );
  }

  if (cfgLoading || !cfg) {
    return (
      <div className="min-h-screen p-8 animate-fade-in">
        <div className="ev-onboarding-loading">
          <Loader2 className="w-4 h-4 animate-spin" /> Loading eval workspace...
        </div>
      </div>
    );
  }

  if (!cfg.repo_url) {
    return (
      <div className="min-h-screen p-8 animate-fade-in ev-onboarding-page">
        <EvalOnboarding config={cfg} onComplete={() => setConfigOpen(false)} />
      </div>
    );
  }

  return (
    <div className="min-h-screen p-8 animate-fade-in">
      {header}

      <div className="space-y-6">
        <ControlDeck
          evalSet={evalSet}
          repoUrl={cfg?.repo_url ?? ""}
          model={cfg?.model ?? "sonnet"}
          runnerEnabled={cfg?.enabled ?? true}
          activeRun={activeRun}
          onStarted={setSelectedRun}
          onConfigure={() => setConfigOpen((open) => !open)}
        />

        {configOpen && (
          <div className="ev-card px-6 pb-6">
            <ConfigForm onSaved={() => setConfigOpen(false)} />
          </div>
        )}

        {tasksError && cfg?.repo_url && (
          <p className="text-sm text-[var(--color-text-dim)]">
            couldn’t load the task set — check the repo (see eval-format.md).
          </p>
        )}

        {tasks && tasks.length > 0 && (
          <TasksSection tasks={tasks} onOpen={setDetailTask} />
        )}

        {selectedRun && <RunDetail runId={selectedRun} />}

        <SandboxPanel />

        <RunsList runs={runs} selectedRun={selectedRun} onSelect={setSelectedRun} />
      </div>

      {detailTask && <TaskDetail t={detailTask} onClose={() => setDetailTask(null)} />}
    </div>
  );
}

export default function EvalsPage() {
  return (
    <Suspense fallback={null}>
      <EvalsPageInner />
    </Suspense>
  );
}
