"use client";

import { ArrowLeft, Check, KeyRound, LogIn, X } from "lucide-react";
import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import type { Connector, ConnectorScope } from "~/lib/api/mcp-connectors";
import { deriveConnectorHealth, type ConnectorHealth } from "~/lib/mcp-connectors-state";
import { useToast } from "~/components/ui/toast";
import { useFocusTrap } from "~/components/ui/use-focus-trap";
import {
  applyProbe,
  buildCreate,
  buildToolSettings,
  initialAddFlowState,
  resolveInput,
  stepBlocker,
  toggleTool,
  type AddFlowState,
} from "./add-flow-state";
import { AddStepAccess } from "./add-step-access";
import { AddStepSource } from "./add-step-source";
import { AddStepTools } from "./add-step-tools";
import { useConnectors } from "./connectors-context";
import { ConnectorGlyph } from "./connector-glyph";
import { ConnectorStatusPill } from "./connector-status-pill";
import { Button, FOCUS_RING } from "./ui";

const STEP_TITLES = ["Where is it?", "Access", "Tools and name"] as const;

/**
 * Three dots. On the done screen the third dot is full only when the
 * connector is actually ready; while it still needs sign-in or a key it is
 * half-filled, so the dots never claim more than the pill does.
 */
function ProgressDots({ step, doneIsReady }: { step: AddFlowState["step"]; doneIsReady: boolean }) {
  const index = step === "done" ? 3 : step - 1;
  return (
    <ol className="flex items-center gap-1.5" aria-label="Progress" data-testid="add-progress">
      {STEP_TITLES.map((title, i) => {
        const half = step === "done" && i === 2 && !doneIsReady;
        const state = half ? "half" : i < index ? "done" : i === index ? "current" : "todo";
        return (
          <li
            key={title}
            aria-current={state === "current" ? "step" : undefined}
            data-state={state}
            className={`h-1.5 overflow-hidden rounded-full transition-[width,background-color] duration-300 ${
              state === "current"
                ? "w-6 bg-[var(--color-success)]"
                : state === "done"
                  ? "w-3 bg-[var(--color-success)]/50"
                  : state === "half"
                    ? "w-3 bg-[var(--color-border-hover)]"
                    : "w-3 bg-[var(--color-border-hover)]"
            }`}
          >
            {state === "half" && <span className="block h-full w-1/2 bg-[var(--color-warning)]" aria-hidden="true" />}
            <span className="sr-only">
              {title} {state === "done" ? "(complete)" : state === "current" ? "(current)" : state === "half" ? "(waiting on you)" : ""}
            </span>
          </li>
        );
      })}
    </ol>
  );
}

/** Eyebrow for the done screen: what the row will say, never "Connected" early. */
function doneEyebrow(health: ConnectorHealth): string {
  if (health.tone === "ok") return "Ready";
  return health.label;
}

/**
 * The add flow: one modal, three steps, progress dots. Step 1 probes on
 * Continue (never while typing). Errors end with a way forward. The done
 * screen is derived from the created connector's health, so a sign-in or
 * key that is still missing is stated honestly with the fix as the primary
 * action. Focus is trapped inside while open.
 */
export function AddConnectorModal({
  open,
  initialScope,
  onClose,
  onCreated,
  onOpenAccess,
}: {
  open: boolean;
  initialScope: ConnectorScope;
  onClose: () => void;
  onCreated: (connector: Connector) => void;
  /** "Add key": close the modal and open the drawer's Access tab. */
  onOpenAccess?: (connector: Connector) => void;
}) {
  const { api, isAdmin, connectors, upsert } = useConnectors();
  const { toast } = useToast();
  const [state, setState] = useState<AddFlowState>(() => initialAddFlowState(initialScope));
  const [created, setCreated] = useState<Connector | null>(null);
  const [signingIn, setSigningIn] = useState(false);
  const dialogRef = useRef<HTMLDivElement>(null);
  const restoreFocus = useRef<HTMLElement | null>(null);
  useFocusTrap(dialogRef, open);

  useEffect(() => {
    if (!open) return;
    restoreFocus.current = document.activeElement as HTMLElement | null;
    setState(initialAddFlowState(initialScope));
    setCreated(null);
    return () => restoreFocus.current?.focus?.();
  }, [open, initialScope]);

  useEffect(() => {
    if (!open) return;
    const onKey = (event: KeyboardEvent) => {
      if (event.key === "Escape" && !state.submitting) onClose();
    };
    document.addEventListener("keydown", onKey);
    return () => document.removeEventListener("keydown", onKey);
  }, [open, onClose, state.submitting]);

  const patch = useCallback((next: Partial<AddFlowState>) => {
    setState((current) => ({ ...current, ...next }));
  }, []);

  const input = useMemo(() => resolveInput(state), [state]);
  const blocker = stepBlocker(state);

  const probe = useCallback(async () => {
    const body =
      input.kind === "url"
        ? { url: input.url }
        : input.kind === "command"
          ? { command: input.command, args: input.args }
          : null;
    if (!body) return;
    patch({ probing: true, probe: null, saveAnyway: false, error: null });
    try {
      const result = await api.probe(body);
      setState((current) => {
        const next = applyProbe(current, result);
        return result.error ? next : { ...next, step: 2 };
      });
    } catch (error) {
      setState((current) =>
        applyProbe(current, {
          transport: input.kind === "command" ? "stdio" : "http",
          auth: "unknown",
          error: (error as Error).message || "We couldn't reach this address",
        }),
      );
    }
  }, [api, input, patch]);

  const finish = useCallback(
    (connector: Connector) => {
      upsert(connector);
      setCreated(connector);
      const health = deriveConnectorHealth(connector);
      // The "ready" toast fires only when the row will read Connected.
      if (health.tone === "ok") toast(`${connector.name} is ready · applies to new chats`, "success");
    },
    [toast, upsert],
  );

  const connect = useCallback(async () => {
    patch({ submitting: true, error: null });
    try {
      const connector = await api.create(buildCreate(state));
      let final = connector;
      if (state.tools.length > 0) {
        try {
          final = await api.updateTools(connector.id, { tools: buildToolSettings(state) });
        } catch {
          /* defaults already applied server-side; the drawer shows the truth */
        }
      }
      onCreated(final);
      finish(final);
      patch({ submitting: false, step: "done" });
    } catch (error) {
      patch({ submitting: false, error: (error as Error).message });
    }
  }, [api, finish, onCreated, patch, state]);

  const signIn = useCallback(async () => {
    if (!created) return;
    setSigningIn(true);
    try {
      const result = await api.signIn(created.id);
      if (result.outcome === "signed_in") {
        finish({ ...created, status: "connected", my_state: result.state });
      } else if (result.outcome === "blocked") {
        window.open(result.url, "_blank", "noopener");
      } else if (result.outcome === "error") {
        toast(`The provider refused sign-in: ${result.message}`, "error", 6000);
      }
    } finally {
      setSigningIn(false);
    }
  }, [api, created, finish, toast]);

  if (!open) return null;

  const stepIndex = state.step === "done" ? 3 : state.step;
  const health = created ? deriveConnectorHealth(created) : null;
  const doneIsReady = health?.tone === "ok";

  return (
    <div
      className="fixed inset-0 z-[100] flex items-end justify-center bg-black/70 p-0 sm:items-center sm:p-6"
      onClick={() => !state.submitting && onClose()}
    >
      <div
        ref={dialogRef}
        role="dialog"
        aria-modal="true"
        aria-labelledby="add-connector-title"
        data-testid="add-connector-modal"
        onClick={(e) => e.stopPropagation()}
        className="flex max-h-[100dvh] w-full max-w-[640px] flex-col overflow-hidden rounded-t-[var(--radius-lg)] border border-[var(--color-border)] bg-[var(--color-bg)] shadow-2xl shadow-black/60 animate-slide-in-up sm:max-h-[90vh] sm:rounded-[var(--radius-lg)] sm:animate-scale-in"
      >
        <header className="flex flex-none items-center gap-3 border-b border-[var(--color-border)] px-5 py-3.5">
          {state.step !== 1 && state.step !== "done" ? (
            <button
              type="button"
              aria-label="Back"
              data-testid="add-back"
              onClick={() => patch({ step: state.step === 3 ? 2 : 1, error: null })}
              className={`-ml-1.5 flex h-9 w-9 items-center justify-center rounded-[8px] text-[var(--color-text-dim)] hover:bg-[var(--color-bg-hover)] hover:text-[var(--color-text)] ${FOCUS_RING}`}
            >
              <ArrowLeft className="h-4 w-4" aria-hidden="true" />
            </button>
          ) : null}
          <div className="min-w-0 flex-1">
            <p
              className={`text-[10.5px] font-medium uppercase tracking-[0.1em] ${
                state.step === "done" && health && health.tone !== "ok" ? "text-[var(--color-warning)]" : "text-[var(--color-text-dim)]"
              }`}
              data-testid="add-eyebrow"
            >
              {state.step === "done" && health ? doneEyebrow(health) : `Add connector · step ${stepIndex} of 3`}
            </p>
            <h2 id="add-connector-title" className="truncate text-[15px] font-semibold text-[var(--color-text)]">
              {state.step === "done" ? created?.name : STEP_TITLES[stepIndex - 1]}
            </h2>
          </div>
          <ProgressDots step={state.step} doneIsReady={Boolean(doneIsReady)} />
          <button
            type="button"
            aria-label="Close"
            onClick={onClose}
            disabled={state.submitting}
            className={`flex h-9 w-9 items-center justify-center rounded-[8px] text-[var(--color-text-dim)] hover:bg-[var(--color-bg-hover)] hover:text-[var(--color-text)] ${FOCUS_RING}`}
          >
            <X className="h-4 w-4" aria-hidden="true" />
          </button>
        </header>

        <div className="min-h-0 flex-1 overflow-y-auto px-5 py-5">
          {state.step === 1 && (
            <AddStepSource
              state={state}
              input={input}
              onChange={patch}
              onSaveAnyway={() => patch({ saveAnyway: true, step: 2 })}
            />
          )}
          {state.step === 2 && <AddStepAccess state={state} input={input} onChange={patch} />}
          {state.step === 3 && (
            <AddStepTools
              state={state}
              isAdmin={isAdmin}
              existing={connectors}
              onChange={patch}
              onToggleTool={(name, enabled) => setState((c) => toggleTool(c, name, enabled))}
            />
          )}
          {state.step === "done" && created && health && (
            <div className="flex flex-col items-center py-6 text-center" data-testid="add-done" data-health={health.tone}>
              <div className="relative">
                <ConnectorGlyph connector={created} size={56} />
                {doneIsReady && (
                  <span className="absolute -bottom-1.5 -right-1.5 flex h-6 w-6 items-center justify-center rounded-full border-2 border-[var(--color-bg)] bg-[var(--color-success)] text-[var(--color-bg)]">
                    <Check className="h-3.5 w-3.5" strokeWidth={3} aria-hidden="true" />
                  </span>
                )}
              </div>
              <div className="mt-3">
                <ConnectorStatusPill health={health} testId="add-done-pill" />
              </div>
              <h3 className="mt-3 text-[16px] font-semibold text-[var(--color-text)]">
                {health.action === "sign_in"
                  ? `Sign in to ${created.name}`
                  : health.action === "add_key"
                    ? `${created.name} needs your key`
                    : health.action === "retry"
                      ? `${created.name} is saved, not reached`
                      : `${created.name} is ready`}
              </h3>
              <p className="mt-1 max-w-sm text-[12.5px] leading-5 text-[var(--color-text-muted)]">
                {health.action === "sign_in"
                  ? "One more step: a sign-in window from the provider. The agent can't use it until then."
                  : health.action === "add_key"
                    ? "Add your key from the Access tab before the agent can use it."
                    : health.action === "retry"
                      ? `${health.detail ?? "We couldn't reach it"}. Retry from its row once the server is up.`
                      : `${created.enabled_tool_count} of ${created.tool_count} tools are on.`}
              </p>
              <dl className="mt-4 grid grid-cols-[auto_1fr] items-center gap-x-3 gap-y-1 text-[11.5px]">
                <dt className="text-[var(--color-text-dim)]">Agent sees it as</dt>
                <dd className="text-left font-mono text-[var(--color-text-muted)]" data-testid="add-done-slug">
                  mcp__{created.slug}__…
                </dd>
              </dl>
              {health.action === "sign_in" && (
                <Button variant="primary" pending={signingIn} onClick={() => void signIn()} data-testid="add-done-sign-in" className="mt-5">
                  <LogIn className="h-3.5 w-3.5" aria-hidden="true" />
                  {signingIn ? "Waiting for sign-in…" : "Sign in"}
                </Button>
              )}
              {health.action === "add_key" && onOpenAccess && (
                <Button variant="primary" onClick={() => onOpenAccess(created)} data-testid="add-done-add-key" className="mt-5">
                  <KeyRound className="h-3.5 w-3.5" aria-hidden="true" />
                  Add key
                </Button>
              )}
            </div>
          )}
          {state.error && (
            <p role="alert" className="mt-4 text-[12px] text-[var(--color-error)]">
              {state.error}
            </p>
          )}
        </div>

        <footer className="flex flex-none items-center justify-between gap-3 border-t border-[var(--color-border)] px-5 py-3.5">
          <p className="min-w-0 truncate text-[11.5px] text-[var(--color-text-dim)]" aria-live="polite" data-testid="add-footer-note">
            {state.step === "done"
              ? "Applies to new chats."
              : // The inline field error already says what blocks; don't say it twice.
                input.kind === "invalid" && state.step === 1
                ? ""
                : blocker ?? (state.step === 3 ? "Applies to new chats." : "")}
          </p>
          <div className="flex flex-none items-center gap-2">
            {state.step === "done" ? (
              <Button variant={doneIsReady ? "primary" : "secondary"} onClick={onClose} data-testid="add-finish">
                {doneIsReady ? "Done" : health?.action === "sign_in" ? "Later" : "Close"}
              </Button>
            ) : (
              <>
                <Button variant="ghost" onClick={onClose} disabled={state.submitting}>
                  Cancel
                </Button>
                {state.step === 1 && (
                  <Button
                    variant="primary"
                    pending={state.probing}
                    disabled={Boolean(blocker)}
                    onClick={() => void probe()}
                    data-testid="add-continue"
                  >
                    {state.probe?.error ? "Try again" : "Continue"}
                  </Button>
                )}
                {state.step === 2 && (
                  <Button variant="primary" disabled={Boolean(blocker)} onClick={() => patch({ step: 3 })} data-testid="add-continue">
                    Continue
                  </Button>
                )}
                {state.step === 3 && (
                  <Button
                    variant="primary"
                    pending={state.submitting}
                    disabled={Boolean(blocker)}
                    onClick={() => void connect()}
                    data-testid="add-connect"
                  >
                    {state.submitting ? "Connecting…" : "Connect"}
                  </Button>
                )}
              </>
            )}
          </div>
        </footer>
      </div>
    </div>
  );
}
