"use client";

/**
 * Eval management (/evals).
 *
 * An eval set (public git repo or /eval-projects path, format: eval-format.md)
 * renders as a browsable question gallery — markdown writeup, prompt, and gold
 * checks per question. "Evaluate Change" runs test proposed knowledge entries
 * in docker; runs show per-check verdicts and full turn-by-turn transcripts.
 */

import { Suspense, useEffect, useState } from "react";
import { useSearchParams } from "next/navigation";
import useSWR from "swr";
import {
  BookOpen,
  CheckCircle2,
  ChevronDown,
  ChevronRight,
  FlaskConical,
  Loader2,
  Save,
  Settings2,
  X,
  XCircle,
} from "lucide-react";
import {
  getEvalConfig,
  getEvalRun,
  listEvalQuestions,
  listEvalRuns,
  putEvalConfig,
  type EvalCheckResult,
  type EvalQuestion,
  type EvalRun,
  type EvalRunQuestion,
} from "~/lib/api";
import { PageHeader } from "~/components/ui/page-header";
import { useToast } from "~/components/ui/toast";
import { Md, fmtNum } from "./_components/Markdown";
import { TranscriptSlideOver } from "./_components/TranscriptView";
import "./evals.css";

/* ─── verdicts ──────────────────────────────────────────────────────────── */

const VERDICT_STYLE: Record<string, { color: string; label: string }> = {
  CORRECT: { color: "var(--color-success)", label: "correct" },
  PARTIAL: { color: "var(--color-warning, #f5a623)", label: "partial" },
  OFF: { color: "#e5484d", label: "wrong answer" },
  UNKNOWN: { color: "var(--color-warning, #f5a623)", label: "no number" },
  UNGRADED: { color: "var(--color-text-dim)", label: "ungraded" },
  ERROR: { color: "#e5484d", label: "run error" },
  SETUP_FAILED: { color: "#e5484d", label: "setup failed" },
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
    : "var(--color-warning, #f5a623)";
  const live = status === "running" || status === "preparing";
  return (
    <span className="inline-flex items-center gap-1.5 text-[11px] uppercase tracking-[0.12em]" style={{ color }}>
      <span className={`w-1.5 h-1.5 rounded-full ${live ? "animate-pulse" : ""}`} style={{ background: color }} />
      {status}
    </span>
  );
}

function CheckChips({ results }: { results: EvalCheckResult[] }) {
  if (!results?.length) return null;
  return (
    <span className="inline-flex flex-wrap gap-1.5">
      {results.map((c) => (
        <span key={c.name} className={`ev-chip ${c.passed ? "ev-chip--pass" : "ev-chip--fail"}`} title={`${c.name} = ${c.value.toLocaleString()} ±${Math.round(c.tolerance * 100)}%`}>
          <span className="n">{c.name}</span>
          {c.passed ? "✓" : "✗"}
        </span>
      ))}
    </span>
  );
}

/* ─── eval set hero + config ────────────────────────────────────────────── */

function setName(repoUrl: string): string {
  if (!repoUrl) return "no eval set";
  const seg = repoUrl.replace(/\.git$/, "").replace(/[/\\]+$/, "").split(/[/\\]/).pop();
  return seg || repoUrl;
}

function ConfigForm({ onSaved }: { onSaved: () => void }) {
  const { toast } = useToast();
  const { data, mutate } = useSWR("eval-config", getEvalConfig);
  const [form, setForm] = useState({ repo_url: "", model: "sonnet", max_questions: 0, prompt_preamble: "" });
  const [savingCfg, setSavingCfg] = useState(false);
  const [loaded, setLoaded] = useState(false);

  useEffect(() => {
    if (data && !loaded) {
      setForm({
        repo_url: data.repo_url ?? "",
        model: data.model ?? "sonnet",
        max_questions: data.max_questions ?? 0,
        prompt_preamble: data.prompt_preamble ?? "",
      });
      setLoaded(true);
    }
  }, [data, loaded]);

  async function save() {
    setSavingCfg(true);
    try {
      await putEvalConfig(form);
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
    "w-full bg-transparent border border-[var(--color-border)] px-3 py-2 text-sm text-[var(--color-text)] placeholder:text-[var(--color-text-dim)] focus:border-[var(--color-border-hover)] focus:outline-none";

  return (
    <div className="grid grid-cols-1 md:grid-cols-2 gap-4 mt-4 pt-4 border-t border-[var(--color-border)]">
      <div className="md:col-span-2">
        <label className="block text-xs text-[var(--color-text-muted)] mb-1.5">
          Repo — public git URL, or a local path under /eval-projects (format: eval-format.md)
        </label>
        <input className={inputCls} value={form.repo_url} onChange={(e) => setForm({ ...form, repo_url: e.target.value })} placeholder="https://github.com/org/eval-set.git  ·  /eval-projects/my-eval-set" />
      </div>
      <div>
        <label className="block text-xs text-[var(--color-text-muted)] mb-1.5">Model</label>
        <input className={inputCls} value={form.model} onChange={(e) => setForm({ ...form, model: e.target.value })} placeholder="sonnet" />
      </div>
      <div>
        <label className="block text-xs text-[var(--color-text-muted)] mb-1.5">Max questions per run (0 = all)</label>
        <input className={inputCls} type="number" min={0} max={100} value={form.max_questions} onChange={(e) => setForm({ ...form, max_questions: Number(e.target.value) || 0 })} />
      </div>
      <div className="md:col-span-2">
        <label className="block text-xs text-[var(--color-text-muted)] mb-1.5">Prompt preamble — prepended to every question (connection to use, output rules)</label>
        <textarea className={`${inputCls} resize-none`} rows={2} value={form.prompt_preamble} onChange={(e) => setForm({ ...form, prompt_preamble: e.target.value })} placeholder='e.g. "Use the SignalPilot MCP tools with connection my_ro_conn."' />
      </div>
      <div>
        <button onClick={save} disabled={savingCfg} className="inline-flex items-center gap-2 px-4 py-2 text-sm border border-[var(--color-border-hover)] text-[var(--color-text)] hover:bg-[var(--color-bg)] disabled:opacity-40 transition-colors">
          {savingCfg ? <Loader2 className="w-3.5 h-3.5 animate-spin" /> : <Save className="w-3.5 h-3.5" strokeWidth={1.5} />}
          Save config
        </button>
      </div>
    </div>
  );
}

function Hero({ questions, setName_, description, repoUrl, model, runnerEnabled, cfgLoaded }: { questions: EvalQuestion[] | undefined; setName_?: string; description?: string; repoUrl: string; model: string; runnerEnabled: boolean; cfgLoaded: boolean }) {
  const [configOpen, setConfigOpen] = useState(false);
  // Auto-open once when config has loaded and no repo is set yet.
  useEffect(() => {
    if (cfgLoaded && !repoUrl) setConfigOpen(true);
  }, [cfgLoaded, repoUrl]);
  const kinds = new Map<string, number>();
  (questions ?? []).forEach((q) => kinds.set(q.kind, (kinds.get(q.kind) ?? 0) + 1));
  const documented = (questions ?? []).filter((q) => q.doc).length;

  return (
    <div className="ev-card p-6">
      <div className="flex items-start justify-between gap-4 flex-wrap">
        <div>
          <div className="flex items-center gap-3">
            <FlaskConical className="w-5 h-5 text-[var(--color-success)]" strokeWidth={1.25} />
            <h2 className="text-2xl font-light tracking-wide text-[var(--color-text)]">{setName_ || setName(repoUrl)}</h2>
          </div>
          <p className="mt-1.5 text-xs text-[var(--color-text-muted)] font-mono">{repoUrl || "configure an eval repo to get started"}</p>
          {description && <p className="mt-1.5 text-sm text-[var(--color-text-muted)]">{description}</p>}
          {questions && (
            <div className="mt-3 flex items-center gap-4 text-xs text-[var(--color-text-muted)]">
              <span><span className="text-[var(--color-text)] text-base">{questions.length}</span> questions</span>
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
        <button onClick={() => setConfigOpen(!configOpen)} className="inline-flex items-center gap-2 px-3 py-1.5 text-xs uppercase tracking-wider border border-[var(--color-border)] text-[var(--color-text-muted)] hover:border-[var(--color-border-hover)] hover:text-[var(--color-text)] transition-colors">
          <Settings2 className="w-3.5 h-3.5" strokeWidth={1.5} />
          {configOpen ? "Close" : "Configure"}
        </button>
      </div>
      {configOpen && <ConfigForm onSaved={() => setConfigOpen(false)} />}
    </div>
  );
}

/* ─── question gallery + detail slide-over ──────────────────────────────── */

function docTitle(q: EvalQuestion): string {
  const m = q.doc.match(/^#\s+(.+)$/m);
  return m ? m[1] : q.title;
}

function QuestionCard({ q, onOpen }: { q: EvalQuestion; onOpen: () => void }) {
  const broken = q.state.startsWith("broken");
  const control = q.kind === "control" || /control/i.test(q.why + q.doc.slice(0, 200));
  return (
    <button className="ev-qcard" onClick={onOpen}>
      <div className="flex items-start justify-between gap-2">
        <span className="text-sm text-[var(--color-text)] leading-snug">{docTitle(q)}</span>
        <ChevronRight className="w-3.5 h-3.5 mt-0.5 flex-shrink-0 text-[var(--color-text-dim)]" />
      </div>
      <p className="mt-1 text-[11px] font-mono text-[var(--color-text-dim)]">{q.id}</p>
      <div className="mt-3 flex items-center gap-1.5 flex-wrap">
        <span className="ev-badge">{q.kind}</span>
        <span className={`ev-badge ${control ? "ev-badge--control" : broken ? "ev-badge--broken" : ""}`}>{control ? "control" : q.state}</span>
        {q.doc && <span className="ev-badge"><BookOpen className="w-2.5 h-2.5" />docs</span>}
      </div>
      <div className="mt-2.5 flex gap-1.5 flex-wrap">
        {q.checks.map((c) => (
          <span key={c.name} className="ev-chip">
            <span className="n">{c.name}</span>
            {fmtNum(c.value)}
            <span className="n">±{Math.round(c.tolerance * 100)}%</span>
          </span>
        ))}
      </div>
    </button>
  );
}

function QuestionDetail({ q, onClose }: { q: EvalQuestion; onClose: () => void }) {
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => e.key === "Escape" && onClose();
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [onClose]);

  return (
    <>
      <div className="ev-overlay" onClick={onClose} />
      <div className="ev-panel">
        <div className="sticky top-0 bg-[var(--color-bg-card)] border-b border-[var(--color-border)] px-6 py-4 flex items-center justify-between">
          <div>
            <code className="text-xs text-[var(--color-text-dim)]">{q.id}</code>
            <div className="flex items-center gap-1.5 mt-1">
              <span className="ev-badge">{q.kind}</span>
              <span className="ev-badge">{q.state}</span>
            </div>
          </div>
          <button onClick={onClose} aria-label="close" className="text-[var(--color-text-dim)] hover:text-[var(--color-text)]">
            <X className="w-4 h-4" />
          </button>
        </div>
        <div className="px-6 py-5 space-y-6">
          {q.doc ? (
            <Md>{q.doc}</Md>
          ) : (
            <p className="text-sm text-[var(--color-text-dim)]">
              No writeup — add <code>docs/{q.id}.md</code> to the eval repo (see eval-format.md).
            </p>
          )}

          <div>
            <h3 className="text-xs uppercase tracking-[0.14em] text-[var(--color-text-dim)] mb-2">Prompt sent to the agent</h3>
            <pre className="ev-raw border border-[var(--color-border)] bg-[var(--color-bg)] p-3">{q.prompt}</pre>
          </div>

          <div>
            <h3 className="text-xs uppercase tracking-[0.14em] text-[var(--color-text-dim)] mb-2">Gold checks</h3>
            <table className="w-full text-left border-collapse text-sm">
              <thead>
                <tr className="text-[10px] uppercase tracking-wider text-[var(--color-text-dim)]">
                  <th className="py-1 pr-4 font-normal">check</th>
                  <th className="py-1 pr-4 font-normal">gold value</th>
                  <th className="py-1 font-normal">tolerance</th>
                </tr>
              </thead>
              <tbody>
                {q.checks.length ? (
                  q.checks.map((c) => (
                    <tr key={c.name} className="border-t border-[var(--color-border)]">
                      <td className="py-1.5 pr-4 font-mono text-xs text-[var(--color-text-muted)]">{c.name}</td>
                      <td className="py-1.5 pr-4 font-mono text-xs text-[var(--color-text)]">{c.value.toLocaleString()}</td>
                      <td className="py-1.5 font-mono text-xs text-[var(--color-text-muted)]">±{Math.round(c.tolerance * 100)}%</td>
                    </tr>
                  ))
                ) : (
                  <tr className="border-t border-[var(--color-border)]">
                    <td colSpan={3} className="py-1.5 text-xs text-[var(--color-text-dim)]">ungraded — no numeric gold</td>
                  </tr>
                )}
              </tbody>
            </table>
          </div>
        </div>
      </div>
    </>
  );
}

/* ─── runs ──────────────────────────────────────────────────────────────── */

function SetupPhaseRow({ phase, runId }: { phase: import("~/lib/api").EvalSetupPhase; runId: string }) {
  const [log, setLog] = useState<string | null>(null);
  const color = phase.status === "ok" ? "var(--color-success)" : phase.status === "failed" ? "#e5484d" : "var(--color-warning,#f5a623)";
  async function toggleLog() {
    if (log !== null) return setLog(null);
    try {
      setLog(await import("~/lib/api").then((m) => m.getEvalSetupLog(runId, phase.state)));
    } catch {
      setLog("(setup log not available)");
    }
  }
  return (
    <div className="border border-[var(--color-border)] bg-[var(--color-bg)] px-3 py-1.5">
      <div className="flex items-center gap-3 text-xs">
        {phase.status === "running" ? (
          <Loader2 className="w-3 h-3 animate-spin" style={{ color }} />
        ) : (
          <span className="w-1.5 h-1.5 rounded-full" style={{ background: color }} />
        )}
        <code className="text-[var(--color-text)]">{phase.state}</code>
        <span className="text-[var(--color-text-dim)] font-mono">{phase.script}</span>
        <span style={{ color }} className="uppercase tracking-wider text-[10px]">{phase.status}</span>
        {phase.duration_s != null && <span className="text-[var(--color-text-dim)]">{phase.duration_s}s</span>}
        {phase.error && <span className="text-[#e5484d] truncate">{phase.error}</span>}
        <button onClick={toggleLog} className="ml-auto text-[var(--color-text-dim)] hover:text-[var(--color-text)] underline underline-offset-2">
          {log !== null ? "hide log" : "log"}
        </button>
      </div>
      {log !== null && <pre className="ev-raw mt-2 border-t border-[var(--color-border)] pt-2">{log.slice(-20000)}</pre>}
    </div>
  );
}

function RunQuestionRow({ q, runId }: { q: EvalRunQuestion; runId: string }) {
  const [open, setOpen] = useState(false);
  const [showTranscript, setShowTranscript] = useState(false);
  return (
    <>
      <tr className="border-t border-[var(--color-border)] cursor-pointer hover:bg-[var(--color-bg)]" onClick={() => setOpen(!open)}>
        <td className="py-2.5 pr-2 text-[var(--color-text-dim)]">
          {open ? <ChevronDown className="w-3.5 h-3.5" /> : <ChevronRight className="w-3.5 h-3.5" />}
        </td>
        <td className="py-2.5 pr-4 text-sm text-[var(--color-text)]">{q.title}</td>
        <td className="py-2.5 pr-4">
          {q.status === "running" ? (
            <span className="inline-flex items-center gap-1.5 text-xs text-[var(--color-warning,#f5a623)]">
              <Loader2 className="w-3 h-3 animate-spin" /> running
            </span>
          ) : q.status === "pending" ? (
            <span className="text-xs text-[var(--color-text-dim)]">queued</span>
          ) : (
            <VerdictBadge verdict={q.verdict} />
          )}
        </td>
        <td className="py-2.5 pr-4"><CheckChips results={q.check_results ?? []} /></td>
        <td className="py-2.5 text-xs text-[var(--color-text-dim)] whitespace-nowrap">{q.duration_s ? `${q.duration_s}s` : ""}</td>
      </tr>
      {open && (
        <tr className="border-t border-[var(--color-border)]">
          <td />
          <td colSpan={4} className="py-3 pr-4">
            <div className="text-[10px] uppercase tracking-[0.14em] text-[var(--color-text-dim)] mb-1.5">final answer</div>
            <div className="border border-[var(--color-border)] bg-[var(--color-bg)] px-4 py-3 max-h-72 overflow-y-auto">
              <Md>{q.answer || "*(no answer captured yet)*"}</Md>
            </div>
            <button
              onClick={(e) => { e.stopPropagation(); setShowTranscript(true); }}
              className="mt-2 text-xs text-[var(--color-text-muted)] hover:text-[var(--color-text)] underline underline-offset-2"
            >
              view full transcript
            </button>
            {showTranscript && (
              <TranscriptSlideOver
                runId={runId}
                questionId={q.id}
                title={q.title}
                onClose={() => setShowTranscript(false)}
              />
            )}
          </td>
        </tr>
      )}
    </>
  );
}

function RunDetail({ runId }: { runId: string }) {
  const { data: run } = useSWR(`eval-run-${runId}`, () => getEvalRun(runId), {
    refreshInterval: (latest) => (latest && (latest.status === "running" || latest.status === "preparing") ? 3000 : 0),
  });
  if (!run) return <div className="ev-card p-5 text-sm text-[var(--color-text-dim)]">loading run…</div>;

  const s = run.summary ?? {};
  const allPass = (s.correct ?? 0) === (s.total ?? 0) && (s.total ?? 0) > 0;
  return (
    <div className="ev-card p-5">
      <div className="flex items-center justify-between flex-wrap gap-2">
        <div>
          <div className="flex items-center gap-3">
            <code className="text-sm text-[var(--color-text)] tracking-wider">{run.id}</code>
            <StatusDot status={run.status} />
          </div>
          <p className="mt-1 text-xs text-[var(--color-text-muted)]">
            Testing proposed {run.doc_titles.length === 1 ? "entry" : "entries"}:{" "}
            <span className="text-[var(--color-text)]">{run.doc_titles.join(", ")}</span>
            {" · "}model {run.model}
          </p>
        </div>
        {run.status === "completed" && (
          <div className="flex items-center gap-3 text-sm">
            {allPass ? <CheckCircle2 className="w-4 h-4 text-[var(--color-success)]" /> : <XCircle className="w-4 h-4 text-[#e5484d]" />}
            <span className="text-[var(--color-text)]">{s.correct ?? 0}/{s.total ?? 0} correct</span>
            {(s.partial ?? 0) > 0 && <span className="text-xs text-[var(--color-warning,#f5a623)]">{s.partial} partial</span>}
            {(s.error ?? 0) > 0 && <span className="text-xs text-[#e5484d]">{s.error} error</span>}
          </div>
        )}
      </div>

      {run.error && <p className="mt-3 text-sm text-[#e5484d]">{run.error}</p>}

      {(run.setup?.length ?? 0) > 0 && (
        <div className="mt-4 space-y-1">
          <div className="text-[10px] uppercase tracking-[0.14em] text-[var(--color-text-dim)]">state setup</div>
          {run.setup!.map((s) => (
            <SetupPhaseRow key={s.state} phase={s} runId={run.id} />
          ))}
        </div>
      )}

      {run.questions.length > 0 && (
        <table className="mt-4 w-full text-left border-collapse">
          <thead>
            <tr className="text-[10px] uppercase tracking-wider text-[var(--color-text-dim)]">
              <th className="w-6" />
              <th className="py-1 pr-4 font-normal">question</th>
              <th className="py-1 pr-4 font-normal">verdict</th>
              <th className="py-1 pr-4 font-normal">gold checks</th>
              <th className="py-1 font-normal">time</th>
            </tr>
          </thead>
          <tbody>
            {run.questions.map((q) => (
              <RunQuestionRow key={q.id} q={q} runId={run.id} />
            ))}
          </tbody>
        </table>
      )}
    </div>
  );
}

/* ─── page ──────────────────────────────────────────────────────────────── */

function EvalsPageInner() {
  const searchParams = useSearchParams();
  const [selectedRun, setSelectedRun] = useState<string | null>(() => searchParams.get("run"));
  const [detailQ, setDetailQ] = useState<EvalQuestion | null>(null);

  const { data: cfg } = useSWR("eval-config", getEvalConfig);
  const { data: evalSet, error: qError } = useSWR(
    cfg?.repo_url ? `eval-questions-${cfg.repo_url}` : null,
    () => listEvalQuestions(),
  );
  const questions = evalSet?.questions;
  const { data: runsData } = useSWR("eval-runs", listEvalRuns, {
    refreshInterval: (latest) =>
      latest?.runs?.some((r: EvalRun) => r.status === "running" || r.status === "preparing") ? 4000 : 15000,
  });
  const runs = runsData?.runs ?? [];

  return (
    <div className="min-h-screen p-8 animate-fade-in">
      <PageHeader
        title="evals"
        subtitle="knowledge"
        description="test proposed knowledge entries against your eval suite before approving"
      />

      <div className="max-w-5xl space-y-6">
        <Hero questions={questions} setName_={evalSet?.name} description={evalSet?.description} repoUrl={cfg?.repo_url ?? ""} model={cfg?.model ?? "sonnet"} runnerEnabled={cfg?.enabled ?? true} cfgLoaded={!!cfg} />

        {qError && cfg?.repo_url && (
          <p className="text-sm text-[var(--color-text-dim)]">
            couldn’t load the question set — check the repo (manifest traps.tsv + prompts/, see eval-format.md).
          </p>
        )}

        {questions && questions.length > 0 && (
          <div className="grid grid-cols-1 md:grid-cols-2 gap-3">
            {questions.map((q) => (
              <QuestionCard key={q.id} q={q} onOpen={() => setDetailQ(q)} />
            ))}
          </div>
        )}

        {selectedRun && <RunDetail runId={selectedRun} />}

        <div className="ev-card p-5">
          <h2 className="text-sm uppercase tracking-[0.15em] text-[var(--color-text-muted)] mb-3">Runs</h2>
          {runs.length === 0 ? (
            <p className="text-sm text-[var(--color-text-dim)] flex items-center gap-2">
              <FlaskConical className="w-4 h-4" strokeWidth={1.5} />
              No runs yet — open a pending knowledge entry and click “Evaluate Change”.
            </p>
          ) : (
            <div className="divide-y divide-[var(--color-border)]">
              {runs.map((r) => {
                const s = r.summary ?? {};
                return (
                  <button
                    key={r.id}
                    onClick={() => setSelectedRun(r.id)}
                    className={`w-full flex items-center justify-between py-2.5 px-2 text-left hover:bg-[var(--color-bg)] transition-colors ${selectedRun === r.id ? "bg-[var(--color-bg)]" : ""}`}
                  >
                    <div className="min-w-0">
                      <code className="text-sm text-[var(--color-text)]">{r.id}</code>
                      <p className="text-xs text-[var(--color-text-muted)] truncate">{r.doc_titles.join(", ") || r.doc_ids.join(", ")}</p>
                    </div>
                    <div className="flex items-center gap-4 flex-shrink-0 ml-4">
                      {r.status === "completed" && (
                        <span className="text-xs text-[var(--color-text-muted)]">{s.correct ?? 0}/{s.total ?? 0} correct</span>
                      )}
                      <StatusDot status={r.status} />
                    </div>
                  </button>
                );
              })}
            </div>
          )}
        </div>
      </div>

      {detailQ && <QuestionDetail q={detailQ} onClose={() => setDetailQ(null)} />}
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
