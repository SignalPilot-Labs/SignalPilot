"use client";

/**
 * Cloud-only inner onboarding component.
 * Imports @clerk/nextjs hooks directly — only rendered when isCloudMode=true.
 * Isolated to this file so the top-level SSR build never pulls in Clerk's
 * browser-only location API during local-mode static generation.
 */

import { useState, useEffect, useRef } from "react";
import { useRouter } from "next/navigation";
import {
  Key,
  Loader2,
  CheckCircle2,
  AlertTriangle,
  Plug,
} from "lucide-react";
import { DashboardSkeleton } from "@/components/ui/skeleton";
import { useUser, useOrganization } from "@clerk/nextjs";
import { useAppAuth } from "@/lib/auth-context";
import { useBackendClient } from "@/lib/backend-client";
import type { ApiKeyCreatedResponse } from "@/lib/backend-client";
import { useOnboardingStatus } from "@/lib/onboarding";
import { ALL_SCOPES } from "@/lib/api-key-scopes";
import { CopyButton } from "@/components/ui/copy-button";
import { CodeBlock } from "@/components/ui/code-block";
import { useToast } from "@/components/ui/toast";
import { TeamStep } from "./team-step";

// ---------------------------------------------------------------------------
// Re-export the step sub-components that the main page used to define inline.
// Rather than duplicating them, we import from the main page module.
// But the main page imports can't be used here (circular). So we define the
// wrappers here and the main page imports them.
// ---------------------------------------------------------------------------

// ---------------------------------------------------------------------------
// MCP URL helper
// ---------------------------------------------------------------------------

function getMcpUrl(): string {
  return (
    process.env.NEXT_PUBLIC_MCP_URL ||
    `${process.env.NEXT_PUBLIC_GATEWAY_URL || "http://localhost:3300"}/mcp`
  );
}

function getClaudeDesktopConfig(mcpUrl: string, apiKey: string): string {
  return JSON.stringify(
    {
      mcpServers: {
        signalpilot: {
          url: mcpUrl,
          headers: {
            Authorization: `Bearer ${apiKey}`,
          },
        },
      },
    },
    null,
    2,
  );
}

// ---------------------------------------------------------------------------
// Step indicator
// ---------------------------------------------------------------------------

const WIZARD_STEP_LABELS = ["welcome", "api key", "mcp connect", "done"];
const TEAM_STEP_LABELS = ["team", "welcome", "api key", "mcp connect", "done"];

function StepIndicator({
  currentStep,
  showTeamStep,
}: {
  currentStep: number;
  showTeamStep: boolean;
}) {
  const labels = showTeamStep ? TEAM_STEP_LABELS : WIZARD_STEP_LABELS;

  return (
    <ol
      aria-label="Onboarding steps"
      className="flex items-center gap-0 mb-10"
    >
      {labels.map((label, idx) => {
        const isActive = idx === currentStep;
        const isDone = idx < currentStep;
        return (
          <li
            key={label}
            aria-current={isActive ? "step" : undefined}
            className="flex items-center"
          >
            <div className="flex flex-col items-center">
              <div
                className={`w-6 h-6 flex items-center justify-center border text-[11px] tracking-wider transition-all ${
                  isActive
                    ? "border-[var(--color-text)] bg-[var(--color-text)] text-[var(--color-bg)]"
                    : isDone
                    ? "border-[var(--color-success)] text-[var(--color-success)]"
                    : "border-[var(--color-border)] text-[var(--color-text-dim)]"
                }`}
              >
                {isDone ? (
                  <CheckCircle2 className="w-3 h-3" />
                ) : (
                  <span>{idx + 1}</span>
                )}
              </div>
              <span
                className={`mt-1.5 text-[11px] tracking-wider uppercase ${
                  isActive
                    ? "text-[var(--color-text)]"
                    : isDone
                    ? "text-[var(--color-success)]"
                    : "text-[var(--color-text-dim)]"
                }`}
              >
                {label}
              </span>
            </div>
            {idx < labels.length - 1 && (
              <div
                className={`h-px w-12 mx-2 mb-4 transition-all ${
                  isDone
                    ? "bg-[var(--color-success)]/50"
                    : "bg-[var(--color-border)]"
                }`}
              />
            )}
          </li>
        );
      })}
    </ol>
  );
}

// ---------------------------------------------------------------------------
// StepWelcome
// ---------------------------------------------------------------------------

function StepWelcome({ onNext }: { onNext: () => void }) {
  return (
    <div className="animate-fade-in">
      <div className="mb-8">
        <h1 className="text-2xl font-light text-[var(--color-text)] tracking-wider mb-3">
          welcome to signalpilot
        </h1>
        <p className="text-[13px] text-[var(--color-text-dim)] tracking-wider leading-relaxed max-w-lg">
          signalpilot provides governed ai database access — letting ai agents
          query your databases through a secure, audited, policy-enforced
          gateway. this wizard will help you create an api key and connect your
          first mcp client.
        </p>
      </div>

      <div className="grid grid-cols-3 gap-px mb-8 bg-[var(--color-border)] border border-[var(--color-border)]">
        {[
          {
            icon: Key,
            label: "api keys",
            desc: "secure token auth for programmatic access",
          },
          {
            icon: Plug,
            label: "mcp connect",
            desc: "plug in claude desktop, cursor, and other mcp clients",
          },
          {
            icon: CheckCircle2,
            label: "governance",
            desc: "every query runs through policy enforcement",
          },
        ].map(({ icon: Icon, label, desc }) => (
          <div
            key={label}
            className="bg-[var(--color-bg-card)] p-5 hover:bg-[var(--color-bg-hover)] transition-all"
          >
            <Icon
              className="w-4 h-4 text-[var(--color-text-dim)] mb-3"
              strokeWidth={1.5}
            />
            <p className="text-[12px] text-[var(--color-text-muted)] uppercase tracking-[0.15em] mb-1.5">
              {label}
            </p>
            <p className="text-[12px] text-[var(--color-text-dim)] tracking-wider leading-relaxed">
              {desc}
            </p>
          </div>
        ))}
      </div>

      <button
        onClick={onNext}
        className="flex items-center gap-2 px-5 py-2.5 bg-[var(--color-text)] text-[var(--color-bg)] text-[12px] tracking-wider uppercase hover:opacity-90 transition-opacity"
      >
        get started
      </button>
    </div>
  );
}

// ---------------------------------------------------------------------------
// StepCreateApiKey
// ---------------------------------------------------------------------------

function StepCreateApiKey({
  onNext,
  onSkip,
  onKeyCreated,
}: {
  onNext: () => void;
  onSkip: () => void;
  onKeyCreated: (key: ApiKeyCreatedResponse) => void;
}) {
  const client = useBackendClient();
  const { toast } = useToast();
  const [name, setName] = useState("");
  const [scopes, setScopes] = useState<string[]>(["read", "query"]);
  const [creating, setCreating] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [createdKey, setCreatedKey] = useState<ApiKeyCreatedResponse | null>(null);

  const L2 = Loader2;

  function toggleScope(scope: string) {
    setScopes((prev) =>
      prev.includes(scope)
        ? prev.filter((s) => s !== scope)
        : [...prev, scope],
    );
  }

  async function handleCreate() {
    if (!name.trim()) {
      setError("key name is required");
      return;
    }
    if (scopes.length === 0) {
      setError("select at least one scope");
      return;
    }
    setCreating(true);
    setError(null);
    try {
      const created = await client.createApiKey(name.trim(), scopes);
      setCreatedKey(created);
      onKeyCreated(created);
      toast("api key created", "success");
    } catch (e) {
      setError(String(e));
      toast("failed to create api key", "error");
    } finally {
      setCreating(false);
    }
  }

  return (
    <div className="animate-fade-in">
      <div className="mb-6">
        <h2 className="text-lg font-light text-[var(--color-text)] tracking-wider mb-2">
          create an api key
        </h2>
        <p className="text-[12px] text-[var(--color-text-dim)] tracking-wider leading-relaxed">
          api keys authenticate your mcp clients and programmatic access to
          signalpilot. you can manage keys anytime in settings.
        </p>
      </div>

      {createdKey ? (
        <div
          role="alert"
          className="border border-[var(--color-success)]/30 bg-[var(--color-success)]/5 p-5 mb-6 animate-fade-in"
        >
          <div className="flex items-start gap-2 mb-4">
            <AlertTriangle
              className="w-3.5 h-3.5 text-[var(--color-warning)] mt-0.5 flex-shrink-0"
              strokeWidth={1.5}
            />
            <p className="text-[12px] text-[var(--color-warning)] tracking-wider leading-relaxed">
              copy this key now. it will not be shown again.
            </p>
          </div>
          <div className="flex items-center gap-3 mb-4">
            <code className="flex-1 px-3 py-2.5 bg-[var(--color-bg)] border border-[var(--color-border)] text-[13px] text-[var(--color-success)] tracking-wider break-all font-mono">
              {createdKey.raw_key}
            </code>
            <CopyButton text={createdKey.raw_key} />
          </div>
          <div className="flex items-center gap-6 text-[11px] text-[var(--color-text-dim)] tracking-wider mb-4">
            <span>name: <span className="text-[var(--color-text-muted)]">{createdKey.name}</span></span>
            <span>prefix: <code className="text-[var(--color-text-muted)]">{createdKey.prefix}</code></span>
            <span>scopes: <span className="text-[var(--color-text-muted)]">{createdKey.scopes.join(", ")}</span></span>
          </div>
        </div>
      ) : (
        <div className="border border-[var(--color-border)] bg-[var(--color-bg-card)] p-5 mb-6">
          <div className="space-y-4">
            <div>
              <label
                htmlFor="onboarding-key-name"
                className="block text-[12px] text-[var(--color-text-dim)] mb-1.5 tracking-wider"
              >
                key name
              </label>
              <input
                id="onboarding-key-name"
                type="text"
                value={name}
                onChange={(e) => setName(e.target.value)}
                onKeyDown={(e) => { if (e.key === "Enter") handleCreate(); }}
                placeholder="e.g. production, ci-pipeline, local-dev"
                autoFocus
                className="w-full px-3 py-2 bg-[var(--color-bg-input)] border border-[var(--color-border)] text-xs focus:outline-none focus:border-[var(--color-text-dim)] tracking-wide"
              />
            </div>
            <div>
              <span className="block text-[12px] text-[var(--color-text-dim)] mb-2 tracking-wider">scopes</span>
              <div className="grid grid-cols-2 gap-2">
                {ALL_SCOPES.map((s) => {
                  const checked = scopes.includes(s.value);
                  return (
                    <label
                      key={s.value}
                      className={`flex items-start gap-2.5 px-3 py-2.5 border cursor-pointer transition-all ${
                        checked
                          ? "border-[var(--color-success)]/40 bg-[var(--color-success)]/5"
                          : "border-[var(--color-border)] hover:border-[var(--color-border-hover)]"
                      }`}
                    >
                      <input
                        type="checkbox"
                        checked={checked}
                        onChange={() => toggleScope(s.value)}
                        className="mt-0.5 accent-[var(--color-success)]"
                      />
                      <div>
                        <span className="text-[12px] text-[var(--color-text-muted)] tracking-wider">{s.label}</span>
                        <p className="text-[11px] text-[var(--color-text-dim)] tracking-wider mt-0.5">{s.description}</p>
                      </div>
                    </label>
                  );
                })}
              </div>
            </div>
            {error && (
              <p className="text-[12px] text-[var(--color-error)] tracking-wider">{error}</p>
            )}
            <button
              onClick={handleCreate}
              disabled={creating || !name.trim()}
              className="flex items-center gap-2 px-4 py-2 bg-[var(--color-text)] text-[var(--color-bg)] text-xs tracking-wider uppercase transition-all hover:opacity-90 disabled:opacity-30"
            >
              {creating ? <L2 className="w-3 h-3 animate-spin" /> : <Key className="w-3 h-3" />}
              create key
            </button>
          </div>
        </div>
      )}

      <div className="flex items-center gap-4">
        <button
          onClick={onNext}
          disabled={!createdKey}
          className="flex items-center gap-2 px-5 py-2.5 bg-[var(--color-text)] text-[var(--color-bg)] text-[12px] tracking-wider uppercase hover:opacity-90 transition-opacity disabled:opacity-30"
        >
          continue
        </button>
        <button
          onClick={onSkip}
          className="text-[12px] text-[var(--color-text-dim)] hover:text-[var(--color-text)] transition-colors tracking-wider underline underline-offset-2"
        >
          skip for now
        </button>
      </div>
    </div>
  );
}

// ---------------------------------------------------------------------------
// StepConnectMcp
// ---------------------------------------------------------------------------

function StepConnectMcp({
  onNext,
  createdKey,
}: {
  onNext: () => void;
  createdKey: ApiKeyCreatedResponse | null;
}) {
  const mcpUrl = getMcpUrl();
  const apiKey = createdKey?.raw_key ?? "sp_your_api_key_here";
  const configSnippet = getClaudeDesktopConfig(mcpUrl, apiKey);

  return (
    <div className="animate-fade-in">
      <div className="mb-6">
        <h2 className="text-lg font-light text-[var(--color-text)] tracking-wider mb-2">
          connect an mcp client
        </h2>
        <p className="text-[12px] text-[var(--color-text-dim)] tracking-wider leading-relaxed">
          add the signalpilot mcp server to your ai client.
        </p>
      </div>
      <div className="border border-[var(--color-border)] bg-[var(--color-bg-card)] p-5 mb-4">
        <p className="text-[11px] text-[var(--color-text-dim)] uppercase tracking-[0.15em] mb-2">mcp server url</p>
        <div className="flex items-center gap-3">
          <code className="flex-1 px-3 py-2.5 bg-[var(--color-bg)] border border-[var(--color-border)] text-[13px] text-[var(--color-success)] tracking-wider font-mono break-all">
            {mcpUrl}
          </code>
          <CopyButton text={mcpUrl} />
        </div>
      </div>
      <div className="mb-4">
        <div className="flex items-center gap-2 mb-2">
          <span className="text-[11px] text-[var(--color-text-dim)] tracking-wider uppercase">file:</span>
          <code className="text-[12px] text-[var(--color-text-muted)] tracking-wider">claude_desktop_config.json</code>
        </div>
        <CodeBlock code={configSnippet} language="json" maxHeight="14rem" showLineNumbers />
      </div>
      <button
        onClick={onNext}
        className="flex items-center gap-2 px-5 py-2.5 bg-[var(--color-text)] text-[var(--color-bg)] text-[12px] tracking-wider uppercase hover:opacity-90 transition-opacity"
      >
        continue
      </button>
    </div>
  );
}

// ---------------------------------------------------------------------------
// StepDone
// ---------------------------------------------------------------------------

function StepDone({
  createdKey,
  onFinish,
}: {
  createdKey: ApiKeyCreatedResponse | null;
  onFinish: () => void;
}) {
  return (
    <div className="animate-fade-in">
      <div className="mb-8">
        <div className="flex items-center gap-3 mb-4">
          <CheckCircle2 className="w-6 h-6 text-[var(--color-success)]" strokeWidth={1.5} />
          <h2 className="text-lg font-light text-[var(--color-text)] tracking-wider">you&apos;re all set</h2>
        </div>
        <p className="text-[12px] text-[var(--color-text-dim)] tracking-wider leading-relaxed mb-6">
          signalpilot is ready to use. here&apos;s what you configured:
        </p>
        <div className="border border-[var(--color-border)] bg-[var(--color-bg-card)] divide-y divide-[var(--color-border)]">
          <div className="flex items-center gap-3 px-5 py-3">
            <Key className="w-3.5 h-3.5 text-[var(--color-text-dim)] flex-shrink-0" strokeWidth={1.5} />
            <span className="flex-1 text-[12px] text-[var(--color-text-dim)] tracking-wider">api key</span>
            {createdKey ? (
              <span className="flex items-center gap-1.5 text-[12px] text-[var(--color-success)] tracking-wider">
                <CheckCircle2 className="w-3 h-3" />
                created ({createdKey.name})
              </span>
            ) : (
              <span className="text-[12px] text-[var(--color-text-dim)] tracking-wider">skipped</span>
            )}
          </div>
          <div className="flex items-center gap-3 px-5 py-3">
            <Plug className="w-3.5 h-3.5 text-[var(--color-text-dim)] flex-shrink-0" strokeWidth={1.5} />
            <span className="flex-1 text-[12px] text-[var(--color-text-dim)] tracking-wider">mcp config reviewed</span>
            <span className="flex items-center gap-1.5 text-[12px] text-[var(--color-success)] tracking-wider">
              <CheckCircle2 className="w-3 h-3" />
              done
            </span>
          </div>
        </div>
      </div>
      <button
        onClick={onFinish}
        className="flex items-center gap-2 px-5 py-2.5 bg-[var(--color-text)] text-[var(--color-bg)] text-[12px] tracking-wider uppercase hover:opacity-90 transition-opacity"
      >
        go to dashboard
      </button>
    </div>
  );
}

// ---------------------------------------------------------------------------
// OnboardingWizard — only called once orgId is set
// ---------------------------------------------------------------------------

function OnboardingWizard({
  step,
  setStep,
  createdKey,
  setCreatedKey,
  router,
  toast,
}: {
  step: number;
  setStep: (s: number) => void;
  createdKey: ApiKeyCreatedResponse | null;
  setCreatedKey: (k: ApiKeyCreatedResponse | null) => void;
  router: ReturnType<typeof useRouter>;
  toast: (msg: string, type: "success" | "error") => void;
}) {
  const { isComplete, markComplete, isLoading } = useOnboardingStatus();

  if (isLoading || isComplete === null) {
    return <DashboardSkeleton />;
  }

  useEffect(() => {
    if (isComplete === true) {
      router.push("/dashboard");
    }
  }, [isComplete, router]);

  if (isComplete === true) {
    return (
      <div className="flex items-center justify-center min-h-[60vh]">
        <Loader2 className="w-4 h-4 animate-spin text-[var(--color-text-dim)]" aria-hidden="true" />
      </div>
    );
  }

  async function handleFinish() {
    try {
      await markComplete();
    } catch {
      toast("could not save onboarding status", "error");
    }
    router.push("/dashboard");
  }

  return (
    <div className="p-8 max-w-2xl animate-fade-in">
      <div className="mb-8">
        <p className="text-[11px] text-[var(--color-text-dim)] uppercase tracking-[0.15em] mb-1">signalpilot</p>
        <p className="text-[12px] text-[var(--color-text-dim)] tracking-wider">setup wizard</p>
      </div>
      <StepIndicator currentStep={step} showTeamStep={false} />
      {step === 0 && <StepWelcome onNext={() => setStep(1)} />}
      {step === 1 && (
        <StepCreateApiKey
          onNext={() => setStep(2)}
          onSkip={() => setStep(2)}
          onKeyCreated={(key) => setCreatedKey(key)}
        />
      )}
      {step === 2 && <StepConnectMcp onNext={() => setStep(3)} createdKey={createdKey} />}
      {step === 3 && <StepDone createdKey={createdKey} onFinish={handleFinish} />}
    </div>
  );
}

// ---------------------------------------------------------------------------
// CloudOnboardingContent — main export
// Gates on useUser().user then useOrganization().organization
// ---------------------------------------------------------------------------

export function CloudOnboardingContent() {
  const router = useRouter();
  const { toast } = useToast();
  const { isCloudMode } = useAppAuth();

  // useUser works even in pending-session window (unlike useAuth().isSignedIn)
  const { user, isLoaded: userLoaded } = useUser();
  const { organization, isLoaded: orgLoaded } = useOrganization();

  const [teamCreated, setTeamCreated] = useState(false);
  const [handoff, setHandoff] = useState(false);
  const [step, setStep] = useState(0);
  const [createdKey, setCreatedKey] = useState<ApiKeyCreatedResponse | null>(null);
  const handoffTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null);

  useEffect(() => {
    return () => {
      if (handoffTimerRef.current !== null) {
        clearTimeout(handoffTimerRef.current);
      }
    };
  }, []);

  function handleTeamCreated() {
    setHandoff(true);
    handoffTimerRef.current = setTimeout(() => {
      setTeamCreated(true);
    }, 180);
  }

  if (!userLoaded || !orgLoaded) {
    return <DashboardSkeleton />;
  }

  useEffect(() => {
    if (userLoaded && !user) {
      router.push("/sign-in");
    }
  }, [userLoaded, user, router]);

  if (userLoaded && !user) {
    return <DashboardSkeleton />;
  }

  const orgId = organization?.id ?? null;
  const showTeamStep = isCloudMode && !orgId && !teamCreated;

  if (showTeamStep) {
    return (
      <div className={`p-8 max-w-2xl ${handoff ? "animate-slide-out-up" : "animate-fade-in"}`}>
        <div className="mb-8">
          <p className="text-[11px] text-[var(--color-text-dim)] uppercase tracking-[0.15em] mb-1">signalpilot</p>
          <p className="text-[12px] text-[var(--color-text-dim)] tracking-wider">setup wizard</p>
        </div>
        <StepIndicator currentStep={0} showTeamStep={true} />
        <TeamStep onTeamCreated={handleTeamCreated} />
      </div>
    );
  }

  return (
    <OnboardingWizard
      step={step}
      setStep={setStep}
      createdKey={createdKey}
      setCreatedKey={setCreatedKey}
      router={router}
      toast={toast}
    />
  );
}
