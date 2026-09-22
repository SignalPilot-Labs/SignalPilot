"use client";

import { useEffect, useState } from "react";
import useSWR, { mutate } from "swr";
import {
  ArrowLeft,
  ArrowRight,
  BellRing,
  Check,
  Database,
  FolderGit2,
  GitBranch,
  Globe2,
  HardDrive,
  LockKeyhole,
  Loader2,
} from "lucide-react";
import { getConnections, getGitHubInstallations, putEvalConfig, type EvalConfig } from "~/lib/api";
import { useToast } from "~/components/ui/toast";
import { usePermissions } from "~/lib/hooks/use-permissions";
import { useAppAuth } from "~/lib/auth-context";
import { ReadOnlyNote } from "~/components/access/read-only-note";
import { RepoPicker, useGitHubConnect } from "./RepoPicker";
import { ProjectRepoFields, projectRepoError } from "./ProjectRepoFields";
import { PolicyStep, RuntimeStep } from "./OnboardingStepPanels";
import {
  draftError,
  draftPayload,
  emailError,
  initialDraft,
  initialSourceKind,
  runtimeStepError,
  sourceStepError,
  type Draft,
  type SourceKind,
} from "./onboardingDraft";

const STEPS = [
  { label: "Eval set", icon: FolderGit2 },
  { label: "dbt project", icon: GitBranch },
  { label: "Runtime", icon: Database },
  { label: "Automation", icon: BellRing },
] as const;

/**
 * With no eval set configured, an admin gets the setup wizard and a member
 * gets a short note: the org admins set evals up.
 */
export function EvalOnboarding(props: { config: EvalConfig; onComplete: () => void }) {
  const { can } = usePermissions();
  if (!can("evals.run")) return <EvalOnboardingMemberNote />;
  return <EvalOnboardingWizard {...props} />;
}

function EvalOnboardingMemberNote() {
  return (
    <section className="ev-onboarding" aria-labelledby="eval-onboarding-title" data-testid="eval-onboarding-member">
      <header className="ev-onboarding-header">
        <div>
          <p className="ev-onboarding-kicker">Evaluation workspace</p>
          <h1 id="eval-onboarding-title">No eval set yet</h1>
          <p>Your org admins connect the eval repository, warehouse, and run policy. Results, runs, and accuracy appear here once a set is configured.</p>
        </div>
      </header>
      <div className="ev-onboarding-body">
        <ReadOnlyNote block>eval setup is an org admin task</ReadOnlyNote>
      </div>
    </section>
  );
}

function EvalOnboardingWizard({
  config,
  onComplete,
}: {
  config: EvalConfig;
  onComplete: () => void;
}) {
  const { toast } = useToast();
  const { isCloudMode } = useAppAuth();
  const { data: connections, error: connectionsError, isLoading: connectionsLoading } = useSWR(
    "connections",
    getConnections,
  );
  const { data: installations, isLoading: installationsLoading } = useSWR(
    "github-installations",
    getGitHubInstallations,
  );
  const [step, setStep] = useState(0);
  const [furthestStep, setFurthestStep] = useState(0);
  const [draft, setDraft] = useState<Draft>(() => initialDraft(config));
  const [sourceKind, setSourceKind] = useState<SourceKind>(() => initialSourceKind(config));
  const [error, setError] = useState<string | null>(null);
  const [saving, setSaving] = useState(false);
  const { connectGitHub, connecting: connectingGitHub } = useGitHubConnect("/evals", setError);

  useEffect(() => {
    setDraft(initialDraft(config));
    setSourceKind(initialSourceKind(config));
  }, [config]);

  function update(patch: Partial<Draft>) {
    setDraft((current) => ({ ...current, ...patch }));
    setError(null);
  }

  function validateCurrentStep(): string | null {
    if (step === 0) return sourceStepError(draft, sourceKind);
    if (step === 1) return projectRepoError(draft.project, isCloudMode);
    if (step === 2) return runtimeStepError(draft);
    if (step === 3) return emailError(draft.notify_emails);
    return null;
  }

  function advance() {
    const message = validateCurrentStep();
    if (message) {
      setError(message);
      return;
    }
    const next = Math.min(step + 1, STEPS.length - 1);
    setError(null);
    setStep(next);
    setFurthestStep((current) => Math.max(current, next));
  }

  async function finish() {
    const message = draftError(draft, sourceKind, isCloudMode);
    if (message) {
      setError(message);
      return;
    }

    setSaving(true);
    setError(null);
    try {
      await putEvalConfig(draftPayload(draft, sourceKind));
      await mutate("eval-config");
      toast("eval set connected", "success");
      onComplete();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Could not save the eval configuration.");
    } finally {
      setSaving(false);
    }
  }

  function chooseSourceKind(kind: SourceKind) {
    if (kind === sourceKind) return;
    setSourceKind(kind);
    update({ repo_url: "", repo_installation_id: null, repo_id: null });
  }

  return (
    <section className="ev-onboarding" aria-labelledby="eval-onboarding-title">
      <header className="ev-onboarding-header">
        <div>
          <p className="ev-onboarding-kicker">Evaluation workspace</p>
          <h1 id="eval-onboarding-title">Connect your eval set</h1>
          <p>Pin the task repository, dbt project, warehouse, and run policy.</p>
        </div>
        <span className="ev-onboarding-count">{step + 1} / {STEPS.length}</span>
      </header>

      <nav className="ev-onboarding-steps" aria-label="Setup progress">
        {STEPS.map((item, index) => {
          const Icon = item.icon;
          const complete = index < step;
          const available = index <= furthestStep;
          return (
            <button
              key={item.label}
              type="button"
              className={index === step ? "is-current" : complete ? "is-complete" : ""}
              disabled={!available || saving}
              onClick={() => {
                setStep(index);
                setError(null);
              }}
              aria-current={index === step ? "step" : undefined}
            >
              <span>{complete ? <Check /> : <Icon />}</span>
              {item.label}
            </button>
          );
        })}
      </nav>

      <div className="ev-onboarding-body">
        {step === 0 && (
          <div className="ev-onboarding-panel" data-testid="onboarding-step-source">
            <div className="ev-onboarding-heading">
              <span>01</span>
              <div>
                <h2>Eval source</h2>
                <p>Choose where SignalPilot reads the evaluation manifest and prompts.</p>
              </div>
            </div>
            <div className="ev-source-kinds" role="group" aria-label="Repository access">
              <button type="button" className={sourceKind === "public" ? "is-selected" : ""} onClick={() => chooseSourceKind("public")}>
                <Globe2 /> <span><strong>Public GitHub</strong><small>Clone over HTTPS</small></span>
              </button>
              <button type="button" className={sourceKind === "private" ? "is-selected" : ""} onClick={() => chooseSourceKind("private")} data-testid="source-kind-private">
                <LockKeyhole /> <span><strong>Private GitHub</strong><small>Use the GitHub App</small></span>
              </button>
              <button type="button" className={sourceKind === "mounted" ? "is-selected" : ""} onClick={() => chooseSourceKind("mounted")}>
                <HardDrive /> <span><strong>Mounted path</strong><small>Read from this host</small></span>
              </button>
            </div>

            {sourceKind === "public" && (
              <label className="ev-onboarding-field">
                <span>Public repository URL</span>
                <input
                  autoFocus
                  value={draft.repo_url}
                  onChange={(event) => update({ repo_url: event.target.value })}
                  placeholder="https://github.com/org/eval-set.git"
                />
              </label>
            )}

            {sourceKind === "mounted" && (
              <label className="ev-onboarding-field">
                <span>Mounted project path</span>
                <input
                  autoFocus
                  value={draft.repo_url}
                  onChange={(event) => update({ repo_url: event.target.value })}
                  placeholder="/eval-projects/northwind"
                />
                <small>The path must remain under /eval-projects.</small>
              </label>
            )}

            {sourceKind === "private" && (
              <RepoPicker
                value={{ url: draft.repo_url, installationId: draft.repo_installation_id, repoId: draft.repo_id }}
                onChange={(next) => update({ repo_url: next.url, repo_installation_id: next.installationId, repo_id: next.repoId })}
                installations={installations}
                installationsLoading={installationsLoading}
                onConnectGitHub={connectGitHub}
                connectingGitHub={connectingGitHub}
                gitSuffix
                connectPrompt="Choose the account and grant access to the repository that contains this eval set."
                testId="eval-repo"
              />
            )}
            <div className="ev-onboarding-manifest">
              <span><Check /> manifest</span>
              <span><Check /> prompts</span>
              <code>eval-format.md</code>
            </div>
          </div>
        )}

        {step === 1 && (
          <div className="ev-onboarding-panel" data-testid="onboarding-step-project">
            <div className="ev-onboarding-heading">
              <span>02</span>
              <div>
                <h2>dbt project repository</h2>
                <p>The eval set runs against this dbt project. SignalPilot clones it for every run.</p>
              </div>
            </div>
            <ProjectRepoFields
              value={draft.project}
              onChange={(project) => update({ project })}
              installations={installations}
              installationsLoading={installationsLoading}
              onConnectGitHub={connectGitHub}
              connectingGitHub={connectingGitHub}
              isCloudMode={isCloudMode}
            />
          </div>
        )}

        {step === 2 && (
          <RuntimeStep
            draft={draft}
            update={update}
            connections={connections}
            connectionsLoading={connectionsLoading}
            connectionsError={connectionsError}
          />
        )}

        {step === 3 && <PolicyStep draft={draft} update={update} />}
      </div>

      <footer className="ev-onboarding-footer">
        <div role="alert" aria-live="polite">{error}</div>
        <div>
          {step > 0 && (
            <button type="button" className="ev-onboarding-back" disabled={saving} onClick={() => {
              setStep((current) => current - 1);
              setError(null);
            }}>
              <ArrowLeft /> Back
            </button>
          )}
          {step < STEPS.length - 1 ? (
            <button type="button" className="ev-onboarding-next" onClick={advance} data-testid="onboarding-continue">
              Continue <ArrowRight />
            </button>
          ) : (
            <button type="button" className="ev-onboarding-next" disabled={saving} onClick={finish} data-testid="onboarding-finish">
              {saving ? <Loader2 className="animate-spin" /> : <Check />}
              Connect eval set
            </button>
          )}
        </div>
      </footer>
    </section>
  );
}
