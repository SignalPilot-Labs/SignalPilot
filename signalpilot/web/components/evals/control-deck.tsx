"use client";

/**
 * The eval command stage: suite name, run/stop, configure, and the live
 * progress dial. Starting and stopping a run needs `evals.run`; members see
 * the same controls disabled with the admin-only tooltip. Configure stays
 * enabled for everyone because the config form renders read-only values for
 * a member.
 */

import Link from "next/link";
import useSWR, { mutate } from "swr";
import { BarChart3, FlaskConical, Loader2, Play, Settings2, Square } from "lucide-react";
import { useState, type CSSProperties } from "react";
import {
  cancelEvalRun,
  getEvalRunProgress,
  startBaselineEvalRun,
  type EvalRun,
  type EvalSetInfo,
} from "~/lib/api";
import { useToast } from "~/components/ui/toast";
import { AdminOnlyControl } from "~/components/access/admin-only-control";

export type ControlDeckProps = {
  evalSet?: EvalSetInfo;
  repoUrl: string;
  /** The dbt project repository. A run needs one; the deck blocks until it is selected. */
  projectRepoUrl: string;
  model: string;
  runnerEnabled: boolean;
  activeRun?: EvalRun;
  onStarted: (runId: string) => void;
  onConfigure: () => void;
};

const STAGES = ["queue", "sandbox", "grade", "evidence"];

function stageIndex(phase: string, live: boolean): number {
  if (phase === "preparing" || phase === "provisioning") return 0;
  if (phase === "agent" || phase === "setup") return 1;
  if (phase === "grading" || phase === "capture") return 2;
  if (phase === "teardown" || phase === "finished") return 3;
  return live ? 1 : -1;
}

function setName(repoUrl: string): string {
  const tail = repoUrl.split("/").pop() || "Evaluation suite";
  return tail.replace(/\.git$/, "");
}

export function ControlDeck({
  evalSet,
  repoUrl,
  projectRepoUrl,
  model,
  runnerEnabled,
  activeRun,
  onStarted,
  onConfigure,
}: ControlDeckProps) {
  const [starting, setStarting] = useState(false);
  const [stopping, setStopping] = useState(false);
  const { toast } = useToast();
  const live = activeRun?.status === "preparing" || activeRun?.status === "running" || activeRun?.status === "cancelling";
  const { data: progress } = useSWR(
    live ? `eval-run-progress-${activeRun.id}` : null,
    () => getEvalRunProgress(activeRun!.id),
    { refreshInterval: 1500 },
  );
  const ready = Boolean(repoUrl && projectRepoUrl);
  const tasks = evalSet?.tasks ?? [];
  const writes = tasks.filter((task) => task.class === "write").length;
  const done = progress?.done ?? 0;
  const total = progress?.total || tasks.length;
  const percent = total ? Math.round((done / total) * 100) : 0;
  const phase = progress?.active?.[0]?.phase ?? progress?.phase ?? (live ? "preparing" : "ready");
  const currentStage = stageIndex(phase, Boolean(live));

  async function runSuite() {
    setStarting(true);
    try {
      const run = await startBaselineEvalRun();
      await mutate("eval-runs");
      onStarted(run.id);
      toast(`eval run started: ${run.id}`, "success");
    } catch (error) {
      toast(`could not start run: ${error instanceof Error ? error.message : "unknown"}`, "error");
    } finally {
      setStarting(false);
    }
  }

  async function stopRun() {
    if (!activeRun) return;
    setStopping(true);
    try {
      await cancelEvalRun(activeRun.id);
      await Promise.all([mutate("eval-runs"), mutate(`eval-run-${activeRun.id}`)]);
      toast("eval cancellation requested", "success");
    } catch (error) {
      toast(`could not stop run: ${error instanceof Error ? error.message : "unknown"}`, "error");
    } finally {
      setStopping(false);
    }
  }

  return (
    <section className={`ev-command-stage ${live ? "is-live" : ""}`} data-testid="eval-control-deck">
      <div className="ev-command-head">
        <div className="min-w-0">
          <div className="flex items-center gap-2.5">
            <FlaskConical className="w-4 h-4 text-[var(--color-success)]" strokeWidth={1.5} />
            <h2>{evalSet?.name || setName(repoUrl)}</h2>
            <span className={`ev-command-state ${live ? "is-live" : ""}`}>{live ? activeRun?.status : "ready"}</span>
          </div>
          <p>{repoUrl || "Configure an eval repository to begin"}</p>
        </div>
        <div className="flex items-center gap-2 flex-wrap">
          <Link href="/evals/accuracy" className="ev-icon-command" title="Open agent accuracy" aria-label="Open agent accuracy">
            <BarChart3 className="w-4 h-4" strokeWidth={1.5} />
          </Link>
          <AdminOnlyControl permission="evals.run">
            <button
              onClick={runSuite}
              disabled={!runnerEnabled || !ready || starting || live}
              className="ev-primary-command"
              data-testid="eval-run-suite"
            >
              {starting ? <Loader2 className="w-3.5 h-3.5 animate-spin" /> : <Play className="w-3.5 h-3.5" strokeWidth={1.5} />}
              Run suite
            </button>
          </AdminOnlyControl>
          {live && (
            <AdminOnlyControl permission="evals.run">
              <button
                onClick={stopRun}
                disabled={stopping || activeRun?.status === "cancelling"}
                className="ev-stop-command"
                data-testid="eval-stop-run"
              >
                {stopping || activeRun?.status === "cancelling" ? <Loader2 className="w-3.5 h-3.5 animate-spin" /> : <Square className="w-3.5 h-3.5" fill="currentColor" />}
                {activeRun?.status === "cancelling" ? "Stopping" : "Stop run"}
              </button>
            </AdminOnlyControl>
          )}
          <button onClick={onConfigure} className="ev-secondary-command" title="Configure evals" data-testid="eval-configure">
            <Settings2 className="w-3.5 h-3.5" strokeWidth={1.5} />
            Configure
          </button>
        </div>
      </div>

      <div className="ev-flightdeck" aria-label={live ? `Run ${percent}% complete` : "Evaluation execution stages"}>
        <div className="ev-flightdeck-grid" aria-hidden="true" />
        <div className="ev-stage-rail">
          {STAGES.map((stage, index) => (
            <div key={stage} className={`ev-stage-node ${currentStage === index ? "is-active" : ""} ${currentStage > index ? "is-done" : ""}`}>
              <span className="ev-stage-signal" />
              <span>{stage}</span>
            </div>
          ))}
          {live && <span className="ev-run-pulse" />}
        </div>
        <div className="ev-flightdeck-readout">
          <div>
            <span className="label">{live ? "active run" : "suite"}</span>
            <strong>{live ? activeRun?.id : `${tasks.length} tasks armed`}</strong>
          </div>
          <div>
            <span className="label">{live ? "progress" : "execution"}</span>
            <strong>{live ? `${done} / ${total}` : `${tasks.length - writes} read / ${writes} write`}</strong>
          </div>
          <div>
            <span className="label">{live ? "current phase" : "model"}</span>
            <strong>{live ? phase : model}</strong>
          </div>
          {live ? (
            <div className="ev-progress-dial" style={{ "--progress": `${percent * 3.6}deg` } as CSSProperties}>
              <span>{percent}%</span>
            </div>
          ) : (
            <AdminOnlyControl permission="evals.run">
              <button
                onClick={runSuite}
                disabled={!runnerEnabled || !ready || starting}
                className="ev-progress-dial ev-progress-launch"
                aria-label="Run the full evaluation suite"
                title="Run the full evaluation suite"
                data-testid="eval-run-dial"
              >
                <span>{starting ? "..." : "RUN"}</span>
              </button>
            </AdminOnlyControl>
          )}
        </div>
      </div>

      {!runnerEnabled && <p className="ev-command-error">Runner disabled: SP_EVAL_RUNNER_IMAGE is not set on the gateway.</p>}
      {!projectRepoUrl && (
        <p className="ev-command-error" data-testid="eval-project-blocker">
          Select the dbt project repository.{" "}
          <button type="button" className="underline underline-offset-2" onClick={onConfigure}>
            Open configuration
          </button>
        </p>
      )}
    </section>
  );
}
