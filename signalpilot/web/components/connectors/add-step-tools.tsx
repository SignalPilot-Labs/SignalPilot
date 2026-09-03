"use client";

import { Building2, Lock, User } from "lucide-react";
import { useEffect, useId, useRef, useState } from "react";
import type { Connector, ConnectorScope, ToolInfo } from "~/lib/api/mcp-connectors";
import { previewSlug, sortToolsByKind } from "~/lib/mcp-connectors-state";
import { resolveInput, type AddFlowState } from "./add-flow-state";
import { ToolRow } from "./tool-row";
import { Eyebrow, Field, FOCUS_RING, Notice, TextInput } from "./ui";

/** True while the list can scroll; drives the bottom fade and the caption. */
function useOverflow(ref: React.RefObject<HTMLElement | null>, deps: unknown[]) {
  const [overflowing, setOverflowing] = useState(false);
  const [atEnd, setAtEnd] = useState(false);
  useEffect(() => {
    const el = ref.current;
    if (!el) return;
    const measure = () => {
      setOverflowing(el.scrollHeight > el.clientHeight + 1);
      setAtEnd(el.scrollTop + el.clientHeight >= el.scrollHeight - 1);
    };
    measure();
    el.addEventListener("scroll", measure);
    const observer = typeof ResizeObserver !== "undefined" ? new ResizeObserver(measure) : null;
    observer?.observe(el);
    return () => {
      el.removeEventListener("scroll", measure);
      observer?.disconnect();
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, deps);
  return { overflowing, atEnd };
}

/**
 * Step 3 — name, who can use it, and the tools with their R3 defaults,
 * grouped On / Off (read-only first within On, writes and destructive first
 * within Off). The list says when it scrolls. Members see the scope
 * selector disabled with the reason, so the org vs. personal idea is taught
 * the first time they add anything.
 */
export function AddStepTools({
  state,
  isAdmin,
  existing,
  onChange,
  onToggleTool,
}: {
  state: AddFlowState;
  isAdmin: boolean;
  existing: Pick<Connector, "slug" | "scope">[];
  onChange: (patch: Partial<AddFlowState>) => void;
  onToggleTool: (name: string, enabled: boolean) => void;
}) {
  const nameId = useId();
  const listRef = useRef<HTMLDivElement>(null);
  const slug = previewSlug(state.name, state.scope, existing);
  const onTools = sortToolsByKind(state.tools.filter((t) => t.enabled), "safe_first");
  const offTools = sortToolsByKind(state.tools.filter((t) => !t.enabled), "risky_first");
  const sandbox = resolveInput(state).kind === "command";
  const { overflowing, atEnd } = useOverflow(listRef, [state.tools.length, onTools.length]);
  const scopes: { value: ConnectorScope; label: string; hint: string; icon: typeof User }[] = [
    { value: "personal", label: "Only me", hint: "A personal connector.", icon: User },
    { value: "org", label: "Everyone in your organization", hint: "Members see it under Organization.", icon: Building2 },
  ];

  const group = (title: string, tools: ToolInfo[], testId: string) =>
    tools.length > 0 && (
      <section aria-label={`${title} tools`} data-testid={testId}>
        <div className="sticky top-0 z-[1] flex items-center gap-2 border-b border-[var(--color-border)] bg-[var(--color-bg-card)] px-3.5 py-1.5">
          <Eyebrow>{title}</Eyebrow>
          <span className="text-[11px] tabular-nums text-[var(--color-text-dim)]">{tools.length}</span>
        </div>
        <ul className="divide-y divide-[var(--color-border)]">
          {tools.map((tool) => (
            <ToolRow key={tool.name} tool={tool} checked={tool.enabled} onCheckedChange={(enabled) => onToggleTool(tool.name, enabled)} />
          ))}
        </ul>
      </section>
    );

  return (
    <div className="space-y-5">
      <div className="grid gap-4 sm:grid-cols-[1fr_1fr]">
        <Field
          label="Name"
          htmlFor={nameId}
          error={slug?.taken ? "You already have a connector with this name." : null}
          hint={
            slug ? (
              <span>
                The agent sees it as{" "}
                <code className="text-[var(--color-text-muted)]">mcp__{slug.slug}__…</code>
                {slug.suffixed && " (an organization connector already uses the bare name)"}
              </span>
            ) : (
              "Shown in lists and in the agent's tool names."
            )
          }
        >
          <TextInput
            id={nameId}
            value={state.name}
            data-testid="add-name"
            onChange={(e) => onChange({ name: e.target.value })}
            placeholder="Linear"
          />
        </Field>
        <div className="space-y-1.5">
          <p className="text-[12px] font-medium text-[var(--color-text-muted)]">Who can use this</p>
          <div role="radiogroup" aria-label="Who can use this" className="space-y-1.5">
            {scopes.map((scope) => {
              const active = state.scope === scope.value;
              const locked = scope.value === "org" && !isAdmin;
              const Icon = scope.icon;
              return (
                <button
                  key={scope.value}
                  type="button"
                  role="radio"
                  aria-checked={active}
                  aria-disabled={locked || undefined}
                  disabled={locked}
                  data-testid={`add-scope-${scope.value}`}
                  onClick={() => onChange({ scope: scope.value })}
                  className={`flex w-full items-center gap-2.5 rounded-[var(--radius-ctl)] border px-3 py-2 text-left transition-colors disabled:cursor-not-allowed ${FOCUS_RING} ${
                    active
                      ? "border-[var(--color-border-active)] bg-[var(--color-bg-hover)]"
                      : "border-[var(--color-border)] bg-[var(--color-bg-card)] hover:border-[var(--color-border-hover)]"
                  } ${locked ? "opacity-60" : ""}`}
                >
                  {locked ? (
                    <Lock className="h-3.5 w-3.5 flex-none text-[var(--color-text-dim)]" aria-hidden="true" />
                  ) : (
                    <Icon className={`h-3.5 w-3.5 flex-none ${active ? "text-[var(--color-success)]" : "text-[var(--color-text-dim)]"}`} aria-hidden="true" />
                  )}
                  <span className="min-w-0">
                    <span className="block text-[12.5px] font-medium text-[var(--color-text)]">{scope.label}</span>
                    <span className="block text-[11px] text-[var(--color-text-dim)]">
                      {locked ? "Ask an admin to add a connector for everyone." : scope.hint}
                    </span>
                  </span>
                </button>
              );
            })}
          </div>
        </div>
      </div>

      <div>
        <div className="mb-2 flex items-end justify-between gap-3">
          <div>
            <p className="text-[12px] font-medium text-[var(--color-text-muted)]">
              Tools
              <span className="ml-1.5 font-normal tabular-nums text-[var(--color-text-dim)]" data-testid="add-tools-count">
                {state.tools.length === 0 ? "none found" : `${onTools.length} of ${state.tools.length} on`}
              </span>
            </p>
            <p className="text-[11.5px] text-[var(--color-text-dim)]">
              Read-only tools start on. Anything that writes starts off until you turn it on.
              {sandbox && " On a sandbox connector these switches are enforced by the agent's tool permissions, not by SignalPilot."}
            </p>
          </div>
        </div>
        {state.tools.length === 0 ? (
          <Notice tone="info">
            {state.probe?.error
              ? "Tools will appear once the server can be reached."
              : "This server doesn't expose any tools yet."}
          </Notice>
        ) : (
          <div className="relative">
            <div
              ref={listRef}
              data-testid="add-tools-list"
              data-overflowing={overflowing}
              className="max-h-[300px] overflow-y-auto rounded-[var(--radius-card)] border border-[var(--color-border)] bg-[var(--color-bg-card)]"
            >
              {group("On", onTools, "add-tools-on")}
              {group("Off", offTools, "add-tools-off")}
            </div>
            {overflowing && !atEnd && (
              <div
                aria-hidden="true"
                className="pointer-events-none absolute inset-x-px bottom-px h-10 rounded-b-[var(--radius-card)] bg-gradient-to-t from-[var(--color-bg-card)] to-transparent"
              />
            )}
            {overflowing && (
              <p className="mt-1.5 text-right text-[11px] text-[var(--color-text-muted)]" data-testid="add-tools-scroll-cue">
                {state.tools.length} tools · scroll for more
              </p>
            )}
          </div>
        )}
      </div>
    </div>
  );
}
