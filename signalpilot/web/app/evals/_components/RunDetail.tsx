"use client";

/** A single eval run: header, stop/export actions, per-task rows, and model coverage. */

import { useState } from "react";
import useSWR, { mutate } from "swr";
import {
  CheckCircle2,
  ChevronDown,
  ChevronRight,
  Download,
  GitBranch,
  Loader2,
  Square,
  XCircle,
} from "lucide-react";
import {
  cancelEvalRun,
  downloadEvalArtifact,
  downloadEvalRunExport,
  getEvalRun,
  getEvalRunProgress,
  getEvalSetupLog,
  type EvalCoverage,
  type EvalCoverageLayer,
  type EvalRunTask,
} from "~/lib/api";
import { useToast } from "~/components/ui/toast";
import { AdminOnlyControl } from "~/components/access/admin-only-control";
import { Md } from "./Markdown";
import { RunProgressBar } from "./SandboxPanel";
import { TranscriptSlideOver } from "./TranscriptView";
import { CheckChips, ClassBadge, StatusDot, VerdictBadge, shortHash } from "./badges";

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

export function RunDetail({ runId }: { runId: string }) {
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
            <AdminOnlyControl permission="evals.run">
              <button
                onClick={stopRun}
                disabled={stopping || run.status === "cancelling"}
                className="ev-stop-command"
              >
                {stopping || run.status === "cancelling" ? <Loader2 className="w-3.5 h-3.5 animate-spin" /> : <Square className="w-3 h-3" fill="currentColor" />}
                {run.status === "cancelling" ? "Stopping" : "Stop run"}
              </button>
            </AdminOnlyControl>
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
