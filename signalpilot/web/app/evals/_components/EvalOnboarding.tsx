"use client";

import { useEffect, useMemo, useState } from "react";
import Link from "next/link";
import useSWR, { mutate } from "swr";
import {
  ArrowLeft,
  ArrowRight,
  BellRing,
  Check,
  Database,
  ExternalLink,
  FolderGit2,
  Loader2,
} from "lucide-react";
import {
  getConnections,
  putEvalConfig,
  type EvalConfig,
} from "~/lib/api";
import { useToast } from "~/components/ui/toast";

type Draft = {
  repo_url: string;
  model: string;
  max_tasks: number;
  prompt_preamble: string;
  connection: string;
  notify_emails: string;
  autorun_on_knowledge_add: boolean;
};

const STEPS = [
  { label: "Eval set", icon: FolderGit2 },
  { label: "Runtime", icon: Database },
  { label: "Automation", icon: BellRing },
] as const;

function initialDraft(config: EvalConfig): Draft {
  return {
    repo_url: config.repo_url ?? "",
    model: config.model || "sonnet",
    max_tasks: config.max_tasks ?? 0,
    prompt_preamble: config.prompt_preamble ?? "",
    connection: config.connection ?? "",
    notify_emails: (config.notify_emails ?? []).join(", "),
    autorun_on_knowledge_add: config.autorun_on_knowledge_add ?? false,
  };
}

function sourceError(value: string): string | null {
  const source = value.trim();
  if (!source) return "Enter an eval repository.";
  if (source.startsWith("/eval-projects/")) {
    const segments = source.slice("/eval-projects/".length).split("/");
    if (segments.every((segment) => segment && segment !== "." && segment !== "..")) return null;
    return "Use a project path without empty, current-directory, or parent-directory segments.";
  }

  try {
    const url = new URL(source);
    if (url.protocol === "https:" && url.hostname && !url.username && !url.password) return null;
  } catch {
    // The mounted-path format is checked before URL parsing.
  }
  return "Use an HTTPS Git URL or a path under /eval-projects.";
}

function emailError(value: string): string | null {
  const addresses = value.split(",").map((email) => email.trim()).filter(Boolean);
  const invalid = addresses.find((email) => !/^[^\s@]+@[^\s@]+\.[^\s@]+$/.test(email));
  return invalid ? `Check the email address: ${invalid}` : null;
}

function draftError(draft: Draft): string | null {
  return sourceError(draft.repo_url)
    || (!draft.connection ? "Select the warehouse connection used for grading." : null)
    || (draft.max_tasks < 0 || draft.max_tasks > 200 ? "Max tasks must be between 0 and 200." : null)
    || emailError(draft.notify_emails);
}

export function EvalOnboarding({
  config,
  onComplete,
}: {
  config: EvalConfig;
  onComplete: () => void;
}) {
  const { toast } = useToast();
  const { data: connections, error: connectionsError, isLoading: connectionsLoading } = useSWR(
    "connections",
    getConnections,
  );
  const [step, setStep] = useState(0);
  const [furthestStep, setFurthestStep] = useState(0);
  const [draft, setDraft] = useState<Draft>(() => initialDraft(config));
  const [error, setError] = useState<string | null>(null);
  const [saving, setSaving] = useState(false);

  useEffect(() => {
    setDraft(initialDraft(config));
  }, [config]);

  const selectedConnection = useMemo(
    () => connections?.find((connection) => connection.name === draft.connection),
    [connections, draft.connection],
  );

  function validateCurrentStep(): string | null {
    if (step === 0) return sourceError(draft.repo_url);
    if (step === 1) {
      if (!draft.connection) return "Select the warehouse connection used for grading.";
      if (draft.max_tasks < 0 || draft.max_tasks > 200) return "Max tasks must be between 0 and 200.";
    }
    if (step === 2) return emailError(draft.notify_emails);
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
    const message = draftError(draft);
    if (message) {
      setError(message);
      return;
    }

    setSaving(true);
    setError(null);
    try {
      await putEvalConfig({
        repo_url: draft.repo_url.trim(),
        model: draft.model,
        max_tasks: draft.max_tasks,
        prompt_preamble: draft.prompt_preamble.trim(),
        connection: draft.connection,
        autorun_on_knowledge_add: draft.autorun_on_knowledge_add,
        notify_emails: draft.notify_emails.split(",").map((email) => email.trim()).filter(Boolean),
      });
      await mutate("eval-config");
      toast("eval set connected", "success");
      onComplete();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Could not save the eval configuration.");
    } finally {
      setSaving(false);
    }
  }

  return (
    <section className="ev-onboarding" aria-labelledby="eval-onboarding-title">
      <header className="ev-onboarding-header">
        <div>
          <p className="ev-onboarding-kicker">Evaluation workspace</p>
          <h1 id="eval-onboarding-title">Connect your eval set</h1>
          <p>Pin the task repository, warehouse, and run policy.</p>
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
          <div className="ev-onboarding-panel">
            <div className="ev-onboarding-heading">
              <span>01</span>
              <div>
                <h2>Eval source</h2>
                <p>Use a public Git repository or a mounted eval project.</p>
              </div>
            </div>
            <label className="ev-onboarding-field">
              <span>Repository</span>
              <input
                autoFocus
                value={draft.repo_url}
                onChange={(event) => {
                  setDraft({ ...draft, repo_url: event.target.value });
                  setError(null);
                }}
                placeholder="https://github.com/org/eval-set.git"
              />
              <small>Mounted projects must use /eval-projects/&lt;name&gt;.</small>
            </label>
            <div className="ev-onboarding-manifest">
              <span><Check /> manifest</span>
              <span><Check /> prompts</span>
              <code>eval-format.md</code>
            </div>
          </div>
        )}

        {step === 1 && (
          <div className="ev-onboarding-panel">
            <div className="ev-onboarding-heading">
              <span>02</span>
              <div>
                <h2>Grading runtime</h2>
                <p>Choose the warehouse and execution limits for every run.</p>
              </div>
            </div>
            <div className="ev-onboarding-grid">
              <label className="ev-onboarding-field">
                <span>Warehouse connection</span>
                <select
                  value={draft.connection}
                  disabled={connectionsLoading || !connections?.length}
                  onChange={(event) => {
                    setDraft({ ...draft, connection: event.target.value });
                    setError(null);
                  }}
                >
                  <option value="">{connectionsLoading ? "Loading connections..." : "Select a connection"}</option>
                  {connections?.map((connection) => (
                    <option key={connection.id} value={connection.name}>
                      {connection.name} ({connection.db_type})
                    </option>
                  ))}
                </select>
                {selectedConnection && (
                  <small>{selectedConnection.database || selectedConnection.host || selectedConnection.db_type}</small>
                )}
              </label>
              <label className="ev-onboarding-field">
                <span>Model</span>
                <select value={draft.model} onChange={(event) => setDraft({ ...draft, model: event.target.value })}>
                  <option value="sonnet">Sonnet</option>
                  <option value="opus">Opus</option>
                  <option value="haiku">Haiku</option>
                </select>
              </label>
              <label className="ev-onboarding-field">
                <span>Max tasks per run</span>
                <input
                  type="number"
                  min={0}
                  max={200}
                  value={draft.max_tasks}
                  onChange={(event) => setDraft({ ...draft, max_tasks: Number(event.target.value) || 0 })}
                />
                <small>Use 0 to run the complete set.</small>
              </label>
              <label className="ev-onboarding-field ev-onboarding-field-wide">
                <span>Prompt preamble</span>
                <textarea
                  rows={3}
                  value={draft.prompt_preamble}
                  onChange={(event) => setDraft({ ...draft, prompt_preamble: event.target.value })}
                  placeholder="Use the SignalPilot MCP tools with connection northwind_ro_conn."
                />
              </label>
            </div>
            {!connectionsLoading && !connections?.length && (
              <div className="ev-onboarding-notice">
                <span>{connectionsError ? "Connections could not be loaded." : "Add a warehouse connection before continuing."}</span>
                <Link href="/connections">Open connections <ExternalLink /></Link>
              </div>
            )}
          </div>
        )}

        {step === 2 && (
          <div className="ev-onboarding-panel">
            <div className="ev-onboarding-heading">
              <span>03</span>
              <div>
                <h2>Run policy</h2>
                <p>Set regression alerts and knowledge-triggered runs.</p>
              </div>
            </div>
            <label className="ev-onboarding-field">
              <span>Notify emails</span>
              <input
                value={draft.notify_emails}
                onChange={(event) => {
                  setDraft({ ...draft, notify_emails: event.target.value });
                  setError(null);
                }}
                placeholder="data-team@acme.com, oncall@acme.com"
              />
              <small>Separate multiple addresses with commas.</small>
            </label>
            <label className="ev-onboarding-toggle">
              <input
                type="checkbox"
                checked={draft.autorun_on_knowledge_add}
                onChange={(event) => setDraft({ ...draft, autorun_on_knowledge_add: event.target.checked })}
              />
              <span aria-hidden="true" />
              <div>
                <strong>Autorun after knowledge changes</strong>
                <small>Run the complete set after an entry is added. Changes coalesce for two minutes.</small>
              </div>
            </label>
            <dl className="ev-onboarding-review">
              <div><dt>Source</dt><dd>{draft.repo_url}</dd></div>
              <div><dt>Connection</dt><dd>{draft.connection}</dd></div>
              <div><dt>Runtime</dt><dd>{draft.model} / {draft.max_tasks === 0 ? "all tasks" : `${draft.max_tasks} tasks`}</dd></div>
            </dl>
          </div>
        )}
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
            <button type="button" className="ev-onboarding-next" onClick={advance}>
              Continue <ArrowRight />
            </button>
          ) : (
            <button type="button" className="ev-onboarding-next" disabled={saving} onClick={finish}>
              {saving ? <Loader2 className="animate-spin" /> : <Check />}
              Connect eval set
            </button>
          )}
        </div>
      </footer>
    </section>
  );
}
