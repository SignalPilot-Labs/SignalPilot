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

import { Suspense, useState } from "react";
import { useSearchParams } from "next/navigation";
import useSWR from "swr";
import { Loader2 } from "lucide-react";
import { getEvalConfig, listEvalRuns, listEvalTasks, type EvalRun, type EvalTask } from "~/lib/api";
import { PageHeader } from "~/components/ui/page-header";
import { useEvalsGate } from "~/components/billing/evals-gate";
import { SandboxPanel } from "./_components/SandboxPanel";
import { ControlDeck } from "./_components/ControlDeck";
import { EvalOnboarding } from "./_components/EvalOnboarding";
import { ConfigForm } from "./_components/ConfigForm";
import { TasksSection } from "./_components/TasksSection";
import { TaskDetail } from "./_components/TaskDetail";
import { RunDetail } from "./_components/RunDetail";
import { RunsList } from "./_components/RunsList";
import "./evals.css";

/* The following code defines the evaluation page. */

function EvalsPageInner() {
  const searchParams = useSearchParams();
  const [selectedRun, setSelectedRun] = useState<string | null>(() => searchParams.get("run"));
  const [detailTask, setDetailTask] = useState<EvalTask | null>(null);
  const [configOpen, setConfigOpen] = useState(false);

  // A free org may call none of the eval routes. Every fetch waits for the
  // plan gate so the plan prompt renders without a burst of 402s.
  const { enabled, blocker } = useEvalsGate();

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
        <div className="max-w-md">
          {blocker ?? (
            <div className="ev-card p-8 text-sm text-[var(--color-text-dim)] flex items-center gap-2">
              <Loader2 className="w-4 h-4 animate-spin" /> loading…
            </div>
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
