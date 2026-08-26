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
  Github,
  Globe2,
  HardDrive,
  LockKeyhole,
  Loader2,
} from "lucide-react";
import {
  getConnections,
  getGitHubInstallations,
  getGitHubInstallUrl,
  getGitHubRepos,
  putEvalConfig,
  type EvalConfig,
} from "~/lib/api";
import { useToast } from "~/components/ui/toast";

type Draft = {
  repo_url: string;
  repo_installation_id: string | null;
  repo_id: number | null;
  model: string;
  max_tasks: number;
  prompt_preamble: string;
  connection: string;
  notify_emails: string;
  autorun_on_knowledge_add: boolean;
};

type SourceKind = "public" | "private" | "mounted";

const STEPS = [
  { label: "Eval set", icon: FolderGit2 },
  { label: "Runtime", icon: Database },
  { label: "Automation", icon: BellRing },
] as const;

function initialDraft(config: EvalConfig): Draft {
  return {
    repo_url: config.repo_url ?? "",
    repo_installation_id: config.repo_installation_id ?? null,
    repo_id: config.repo_id ?? null,
    model: config.model || "sonnet",
    max_tasks: config.max_tasks ?? 0,
    prompt_preamble: config.prompt_preamble ?? "",
    connection: config.connection ?? "",
    notify_emails: (config.notify_emails ?? []).join(", "),
    autorun_on_knowledge_add: config.autorun_on_knowledge_add ?? false,
  };
}

function initialSourceKind(config: EvalConfig): SourceKind {
  if (config.repo_installation_id) return "private";
  if (config.repo_url?.startsWith("/eval-projects/")) return "mounted";
  return "public";
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
    if (url.protocol === "https:" && url.hostname === "github.com" && !url.username && !url.password) return null;
  } catch {
    // The mounted-path format is checked before URL parsing.
  }
  return "Use a GitHub HTTPS URL or a path under /eval-projects.";
}

function emailError(value: string): string | null {
  const addresses = value.split(",").map((email) => email.trim()).filter(Boolean);
  const invalid = addresses.find((email) => !/^[^\s@]+@[^\s@]+\.[^\s@]+$/.test(email));
  return invalid ? `Check the email address: ${invalid}` : null;
}

function draftError(draft: Draft, sourceKind: SourceKind): string | null {
  return (sourceKind === "private" && (!draft.repo_installation_id || !draft.repo_id)
    ? "Select a repository from a connected GitHub account."
    : sourceError(draft.repo_url))
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
  const [connectingGitHub, setConnectingGitHub] = useState(false);
  const { data: githubRepos, isLoading: reposLoading } = useSWR(
    sourceKind === "private" && draft.repo_installation_id
      ? `github-repos-${draft.repo_installation_id}`
      : null,
    () => getGitHubRepos(draft.repo_installation_id as string),
  );

  useEffect(() => {
    setDraft(initialDraft(config));
    setSourceKind(initialSourceKind(config));
  }, [config]);

  const selectedConnection = useMemo(
    () => connections?.find((connection) => connection.name === draft.connection),
    [connections, draft.connection],
  );

  function validateCurrentStep(): string | null {
    if (step === 0) {
      if (sourceKind === "private" && (!draft.repo_installation_id || !draft.repo_id)) {
        return "Select a repository from a connected GitHub account.";
      }
      return sourceError(draft.repo_url);
    }
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
    const message = draftError(draft, sourceKind);
    if (message) {
      setError(message);
      return;
    }

    setSaving(true);
    setError(null);
    try {
      await putEvalConfig({
        repo_url: draft.repo_url.trim(),
        repo_installation_id: sourceKind === "private" ? draft.repo_installation_id : null,
        repo_id: sourceKind === "private" ? draft.repo_id : null,
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

  function chooseSourceKind(kind: SourceKind) {
    if (kind === sourceKind) return;
    setSourceKind(kind);
    setDraft({
      ...draft,
      repo_url: "",
      repo_installation_id: null,
      repo_id: null,
    });
    setError(null);
  }

  async function connectGitHub() {
    setConnectingGitHub(true);
    setError(null);
    try {
      sessionStorage.setItem("sp_github_return_to", "/evals");
      const { install_url } = await getGitHubInstallUrl();
      window.location.assign(install_url);
    } catch (err) {
      sessionStorage.removeItem("sp_github_return_to");
      setError(err instanceof Error ? err.message : "Could not start the GitHub connection.");
      setConnectingGitHub(false);
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
                <p>Choose where SignalPilot reads the evaluation manifest and prompts.</p>
              </div>
            </div>
            <div className="ev-source-kinds" role="group" aria-label="Repository access">
              <button type="button" className={sourceKind === "public" ? "is-selected" : ""} onClick={() => chooseSourceKind("public")}>
                <Globe2 /> <span><strong>Public GitHub</strong><small>Clone over HTTPS</small></span>
              </button>
              <button type="button" className={sourceKind === "private" ? "is-selected" : ""} onClick={() => chooseSourceKind("private")}>
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
                  onChange={(event) => {
                    setDraft({ ...draft, repo_url: event.target.value });
                    setError(null);
                  }}
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
                  onChange={(event) => {
                    setDraft({ ...draft, repo_url: event.target.value });
                    setError(null);
                  }}
                  placeholder="/eval-projects/northwind"
                />
                <small>The path must remain under /eval-projects.</small>
              </label>
            )}

            {sourceKind === "private" && (
              <div className="ev-private-source">
                {installationsLoading ? (
                  <div className="ev-private-loading"><Loader2 className="animate-spin" /> Loading GitHub accounts...</div>
                ) : installations?.length ? (
                  <>
                    <div className="ev-private-grid">
                      <label className="ev-onboarding-field">
                        <span>GitHub account</span>
                        <select
                          value={draft.repo_installation_id ?? ""}
                          onChange={(event) => {
                            setDraft({ ...draft, repo_installation_id: event.target.value || null, repo_id: null, repo_url: "" });
                            setError(null);
                          }}
                        >
                          <option value="">Select an account</option>
                          {installations.map((installation) => (
                            <option key={installation.id} value={installation.id}>{installation.github_account_login}</option>
                          ))}
                        </select>
                      </label>
                      <label className="ev-onboarding-field">
                        <span>Repository</span>
                        <select
                          value={draft.repo_id ?? ""}
                          disabled={!draft.repo_installation_id || reposLoading}
                          onChange={(event) => {
                            const repo = githubRepos?.find((item) => item.id === Number(event.target.value));
                            setDraft({
                              ...draft,
                              repo_id: repo?.id ?? null,
                              repo_url: repo ? `https://github.com/${repo.full_name}.git` : "",
                            });
                            setError(null);
                          }}
                        >
                          <option value="">{reposLoading ? "Loading repositories..." : "Select a repository"}</option>
                          {githubRepos?.map((repo) => (
                            <option key={repo.id} value={repo.id}>{repo.full_name}{repo.private ? " (private)" : ""}</option>
                          ))}
                        </select>
                      </label>
                    </div>
                    <button type="button" className="ev-connect-github-secondary" disabled={connectingGitHub} onClick={connectGitHub}>
                      <Github /> Connect another GitHub account
                    </button>
                  </>
                ) : (
                  <div className="ev-connect-github">
                    <Github />
                    <div><strong>Connect GitHub</strong><p>Choose the account and grant access to the repository that contains this eval set.</p></div>
                    <button type="button" disabled={connectingGitHub} onClick={connectGitHub}>
                      {connectingGitHub ? <Loader2 className="animate-spin" /> : <Github />}
                      Connect GitHub
                    </button>
                  </div>
                )}
              </div>
            )}
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
