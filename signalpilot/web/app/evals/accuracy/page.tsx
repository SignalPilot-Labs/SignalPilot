"use client";

import Link from "next/link";
import { useMemo, useState, type CSSProperties } from "react";
import useSWR from "swr";
import {
  AlertTriangle,
  ArrowLeft,
  ArrowUpRight,
  CircleDot,
  Search,
  ShieldCheck,
  TrendingDown,
  TrendingUp,
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
  getEvalAccuracy,
  getEvalAvailability,
  listEvalRuns,
  listEvalTasks,
  type EvalRegression,
  type EvalTaskPerformance,
} from "~/lib/api";
import { PageHeader } from "~/components/ui/page-header";
import { MartCoverageTopology } from "./mart-coverage-topology";
import "../evals.css";
import "./accuracy.css";

type TrendPoint = {
  run_id: string;
  label: string;
  accuracy: number;
  coverage: number | null;
  regressed: boolean;
  passed: number;
  total: number;
};

function median(values: number[]): number | null {
  if (!values.length) return null;
  const sorted = [...values].sort((a, b) => a - b);
  const middle = Math.floor(sorted.length / 2);
  return sorted.length % 2 ? sorted[middle] : (sorted[middle - 1] + sorted[middle]) / 2;
}

function formatDuration(seconds: number | null): string {
  if (seconds == null) return "no data";
  if (seconds < 60) return `${seconds.toFixed(0)}s`;
  return `${Math.floor(seconds / 60)}m ${Math.round(seconds % 60)}s`;
}

function TrendTooltip({ active, payload }: { active?: boolean; payload?: Array<{ payload: TrendPoint }> }) {
  if (!active || !payload?.length) return null;
  const point = payload[0].payload;
  return (
    <div className="acc-tooltip">
      <code>{point.run_id}</code>
      <strong>{point.accuracy.toFixed(1)}% accuracy</strong>
      <span>{point.passed}/{point.total} tasks passed</span>
      {point.coverage != null && <span>{point.coverage.toFixed(1)}% mart coverage</span>}
    </div>
  );
}

function Metric({ label, value, note, tone = "default" }: { label: string; value: string; note: string; tone?: "default" | "good" | "bad" }) {
  return (
    <div className={`acc-metric is-${tone}`}>
      <span>{label}</span>
      <strong>{value}</strong>
      <p>{note}</p>
    </div>
  );
}

function InsightStrip({ tasks, latest, baseline, regression }: {
  tasks: EvalTaskPerformance[];
  latest: number | null;
  baseline: number | null;
  regression?: EvalRegression;
}) {
  const strongest = [...tasks].sort((a, b) => b.pass_rate_pct - a.pass_rate_pct || b.attempts - a.attempts)[0];
  const weakest = tasks.find((task) => task.attempts >= 2) ?? tasks[0];
  const delta = latest != null && baseline != null ? latest - baseline : null;
  return (
    <section className="acc-insights" aria-label="Performance insights">
      <div className="acc-insight-lead">
        {delta == null ? <CircleDot /> : delta >= 0 ? <TrendingUp /> : <TrendingDown />}
        <div>
          <span>Current signal</span>
          <strong>
            {delta == null
              ? "Establishing a comparable baseline"
              : delta >= 0
                ? `${delta.toFixed(1)} points above the trailing median`
                : `${Math.abs(delta).toFixed(1)} points below the trailing median`}
          </strong>
        </div>
      </div>
      <div className="acc-insight">
        <span>Most reliable</span>
        <strong>{strongest?.title || "Awaiting task history"}</strong>
        {strongest && <small>{strongest.pass_rate_pct.toFixed(0)}% across {strongest.attempts} attempts</small>}
      </div>
      <div className="acc-insight">
        <span>Needs attention</span>
        <strong>{weakest?.title || "Awaiting task history"}</strong>
        {weakest && <small>{weakest.pass_rate_pct.toFixed(0)}% pass rate</small>}
      </div>
      <div className="acc-insight">
        <span>Regression watch</span>
        <strong>{regression ? `${regression.drop_pct.toFixed(1)} point drop` : "No detected regression"}</strong>
        <small>{regression ? `${regression.flipped_tasks.length} tasks flipped` : "Latest comparable run is stable"}</small>
      </div>
    </section>
  );
}

function TaskReliability({ tasks }: { tasks: EvalTaskPerformance[] }) {
  const [query, setQuery] = useState("");
  const [classFilter, setClassFilter] = useState<"all" | "read" | "write">("all");
  const filtered = tasks.filter((task) => {
    if (classFilter !== "all" && task.class !== classFilter) return false;
    const needle = query.trim().toLowerCase();
    return !needle || task.title.toLowerCase().includes(needle) || task.task_id.toLowerCase().includes(needle);
  });
  return (
    <section className="acc-section">
      <div className="acc-section-head">
        <div>
          <span className="acc-eyebrow">Task reliability</span>
          <h2>Where the agent succeeds and fails</h2>
          <p>Pass rates use the most recent 50 completed or failed runs.</p>
        </div>
        <div className="acc-table-tools">
          <div className="acc-segments" aria-label="Filter by task class">
            {(["all", "read", "write"] as const).map((value) => <button key={value} className={classFilter === value ? "is-on" : ""} onClick={() => setClassFilter(value)}>{value}</button>)}
          </div>
          <div className="acc-search"><Search /><input value={query} onChange={(event) => setQuery(event.target.value)} placeholder="Find a task" aria-label="Find a task" /></div>
        </div>
      </div>
      <div className="acc-task-table">
        <div className="acc-task-head"><span>task</span><span>reliability</span><span>outcomes</span><span>mean time</span><span>latest</span></div>
        {filtered.map((task) => (
          <Link href={`/evals?run=${task.last_run_id}`} className="acc-task-row" key={task.task_id}>
            <div><strong>{task.title}</strong><code>{task.task_id}</code></div>
            <div className="acc-rate"><span><i style={{ width: `${task.pass_rate_pct}%` }} /></span><strong>{task.pass_rate_pct.toFixed(0)}%</strong></div>
            <div className="acc-outcomes"><span className="good">{task.correct} pass</span><span>{task.partial} partial</span><span className="bad">{task.off + task.errors} fail</span></div>
            <span>{formatDuration(task.avg_duration_s)}</span>
            <span className={`acc-verdict is-${task.last_verdict.toLowerCase()}`}>{task.last_verdict.toLowerCase()}</span>
          </Link>
        ))}
      </div>
      {!filtered.length && <p className="acc-no-results">No tasks match the selected filters.</p>}
    </section>
  );
}

export default function AccuracyPage() {
  const { data: availability, isLoading } = useSWR("eval-availability", getEvalAvailability);
  const enabled = availability?.enabled === true;
  const { data: accuracy } = useSWR(enabled ? "eval-accuracy" : null, getEvalAccuracy, { refreshInterval: 30000 });
  const { data: runs } = useSWR(enabled ? "eval-runs" : null, listEvalRuns);
  const { data: evalSet } = useSWR(enabled ? "eval-tasks-accuracy" : null, listEvalTasks);
  const history = useMemo(
    () => [...(accuracy?.history ?? [])].sort((a, b) => b.created_at.localeCompare(a.created_at)),
    [accuracy],
  );
  const regressions = useMemo(() => accuracy?.regressions ?? [], [accuracy]);
  const taskPerformance = useMemo(() => accuracy?.task_performance ?? [], [accuracy]);
  const latest = history[0];
  const baseline = median(history.slice(1, 6).map((point) => point.accuracy_pct));
  const delta = latest && baseline != null ? latest.accuracy_pct - baseline : null;
  const latestCoverageRun = runs?.runs.find((run) => run.coverage?.models?.length);
  const coverageModels = latestCoverageRun?.coverage?.models ?? [];
  const martCoverage = latestCoverageRun?.coverage?.marts_pct ?? latest?.coverage_pct ?? null;
  const averageDuration = median(taskPerformance.map((task) => task.avg_duration_s).filter((value): value is number => value != null));
  const points = useMemo<TrendPoint[]>(() => {
    const regressedRuns = new Set(regressions.map((regression) => regression.run_id));
    return [...history].reverse().map((point) => ({
      run_id: point.run_id,
      label: new Date(point.created_at).toLocaleDateString("en-US", { month: "short", day: "numeric" }),
      accuracy: point.accuracy_pct,
      coverage: point.coverage_pct,
      regressed: regressedRuns.has(point.run_id),
      passed: point.tasks_passed,
      total: point.tasks_total,
    }));
  }, [history, regressions]);

  if (isLoading || !availability) return <div className="min-h-screen p-8 text-sm text-[var(--color-text-dim)]">Loading accuracy...</div>;
  if (!enabled) return <div className="min-h-screen p-8"><PageHeader title="accuracy" subtitle="evals" description="agent performance and dbt mart coverage" /><p className="text-sm text-[var(--color-text-muted)]">Evals are not enabled for this workspace.</p></div>;

  return (
    <main className="min-h-screen p-8 animate-fade-in acc-page">
      <div className="acc-title-row">
        <PageHeader title="accuracy" subtitle="evals" description="agent performance, regressions, and dbt mart coverage" />
        <Link href="/evals" className="acc-back"><ArrowLeft /> Eval control</Link>
      </div>

      <section className="acc-overview">
        <div className="acc-score">
          <div
            className="acc-score-ring"
            style={{ "--score": `${(latest?.accuracy_pct ?? 0) * 3.6}deg` } as CSSProperties}
            role="img"
            aria-label={latest ? `${latest.accuracy_pct.toFixed(0)} percent agent accuracy` : "Agent accuracy unavailable"}
          >
            <output className="acc-score-value">
              {latest ? `${latest.accuracy_pct.toFixed(0)}%` : "--"}
            </output>
          </div>
          <div>
            <span className="acc-eyebrow">Agent confidence</span>
            <h1>{latest ? (latest.accuracy_pct >= 90 ? "Production-ready signal" : latest.accuracy_pct >= 75 ? "Stable with visible gaps" : "Intervention recommended") : "Awaiting the first run"}</h1>
            <p>{latest ? `${latest.tasks_passed} of ${latest.tasks_total} graded tasks passed in the latest run.` : "Run the evaluation suite to establish a performance baseline."}</p>
          </div>
        </div>
        <div className="acc-metrics">
          <Metric label="vs trailing median" value={delta == null ? "--" : `${delta >= 0 ? "+" : ""}${delta.toFixed(1)} pt`} note={baseline == null ? "Needs two comparable runs" : `${baseline.toFixed(1)}% trailing median`} tone={delta == null ? "default" : delta >= 0 ? "good" : "bad"} />
          <Metric label="mart coverage" value={martCoverage == null ? "--" : `${martCoverage.toFixed(0)}%`} note={coverageModels.length ? `${coverageModels.filter((model) => model.layer === "marts" && model.covered).length} covered marts` : "Complete a project-backed run"} />
          <Metric label="task latency" value={formatDuration(averageDuration)} note="Median of task mean times" />
          <Metric label="regressions" value={String(regressions.length)} note={regressions.length ? "Detected in retained history" : "No drops detected"} tone={regressions.length ? "bad" : "good"} />
        </div>
      </section>

      <InsightStrip tasks={taskPerformance} latest={latest?.accuracy_pct ?? null} baseline={baseline} regression={regressions[0]} />

      <section className="acc-section acc-trend">
        <div className="acc-section-head">
          <div><span className="acc-eyebrow">Performance history</span><h2>Accuracy and mart coverage</h2><p>Regression markers identify statistically comparable drops.</p></div>
          <div className="acc-legend"><span><i className="accuracy" /> accuracy</span><span><i className="coverage" /> coverage</span><span><i className="regression" /> regression</span></div>
        </div>
        {points.length < 2 ? <div className="acc-chart-empty"><TrendingUp /><span>Two completed runs are required for a trend.</span></div> : (
          <ResponsiveContainer width="100%" height={300}>
            <LineChart data={points} margin={{ top: 10, right: 10, left: -15, bottom: 0 }}>
              <CartesianGrid stroke="var(--color-border)" strokeDasharray="2 6" vertical={false} />
              <XAxis dataKey="label" tick={{ fontSize: 10, fill: "var(--color-text-dim)" }} tickLine={false} axisLine={false} />
              <YAxis domain={[0, 100]} tick={{ fontSize: 10, fill: "var(--color-text-dim)" }} tickLine={false} axisLine={false} />
              <Tooltip content={<TrendTooltip />} cursor={{ stroke: "var(--color-border-hover)" }} />
              <Line type="monotone" dataKey="coverage" stroke="#52a9a1" strokeDasharray="5 5" strokeWidth={1.5} dot={false} connectNulls isAnimationActive />
              <Line type="monotone" dataKey="accuracy" stroke="var(--color-success)" strokeWidth={2} dot={(props) => { const point = props.payload as TrendPoint; return <circle key={`${props.cx}-${props.cy}`} cx={props.cx} cy={props.cy} r={point.regressed ? 5 : 3} fill={point.regressed ? "#e5484d" : "var(--color-success)"} />; }} isAnimationActive />
            </LineChart>
          </ResponsiveContainer>
        )}
      </section>

      <MartCoverageTopology models={coverageModels} tasks={evalSet?.tasks ?? []} />
      <TaskReliability tasks={taskPerformance} />

      <section className="acc-section">
        <div className="acc-section-head"><div><span className="acc-eyebrow">Regression ledger</span><h2>Detected performance drops</h2><p>Attribution names a knowledge entry only when it is the sole changed input.</p></div></div>
        <div className="acc-regressions">
          {!regressions.length && <div className="acc-regression-empty"><ShieldCheck /><span>No regressions detected.</span></div>}
          {regressions.map((regression) => (
            <Link href={`/evals?run=${regression.run_id}`} key={regression.id} className="acc-regression-row">
              <AlertTriangle />
              <div><strong>{regression.drop_pct.toFixed(1)} point accuracy drop</strong><span>{regression.flipped_tasks.length} tasks flipped{regression.sole_change && regression.suspected_doc_ids[0] ? ` after ${regression.suspected_doc_ids[0]}` : ""}</span></div>
              <code>{regression.run_id}</code>
              <time>{new Date(regression.created_at).toLocaleDateString()}</time>
              <ArrowUpRight />
            </Link>
          ))}
        </div>
      </section>
    </main>
  );
}
