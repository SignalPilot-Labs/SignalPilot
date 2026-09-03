"use client";

import { AlertTriangle, Globe, Loader2, Terminal } from "lucide-react";
import { useId } from "react";
import { hostOf, type ServerInput } from "~/lib/mcp-connectors-state";
import type { AddFlowState } from "./add-flow-state";
import { FOCUS_RING, Notice, TextInput } from "./ui";

const EXAMPLES: { label: string; value: string }[] = [
  { label: "https://mcp.linear.app/mcp", value: "https://mcp.linear.app/mcp" },
  { label: "npx -y @modelcontextprotocol/server-github", value: "npx -y @modelcontextprotocol/server-github" },
];

/**
 * Step 1 — one field that accepts an address or a command. The parser sets
 * the Address · Command indicator; the user can flip it. Nothing reshapes
 * itself while they type; the probe runs when they continue.
 */
export function AddStepSource({
  state,
  input,
  onChange,
  onSaveAnyway,
}: {
  state: AddFlowState;
  input: ServerInput;
  onChange: (patch: Partial<AddFlowState>) => void;
  onSaveAnyway: () => void;
}) {
  const inputId = useId();
  const kind = input.kind === "url" ? "url" : input.kind === "command" ? "command" : null;
  const failed = Boolean(state.probe?.error) && !state.probing;

  return (
    <div className="space-y-4">
      <div className="space-y-1.5">
        <label htmlFor={inputId} className="block text-[12px] font-medium text-[var(--color-text-muted)]">
          Server URL or command
        </label>
        <div className="relative">
          <TextInput
            id={inputId}
            mono
            autoFocus
            autoComplete="off"
            spellCheck={false}
            value={state.raw}
            invalid={input.kind === "invalid"}
            placeholder="https://mcp.example.com/mcp"
            data-testid="add-source-input"
            onChange={(e) => onChange({ raw: e.target.value, probe: null, saveAnyway: false })}
            className="min-h-[46px] pr-[150px] text-[13px]"
          />
          <div
            role="radiogroup"
            aria-label="Treat this as"
            className="absolute right-1.5 top-1/2 flex -translate-y-1/2 items-center rounded-[8px] border border-[var(--color-border)] bg-[var(--color-bg-card)] p-0.5"
          >
            {(["url", "command"] as const).map((mode) => {
              const active = (state.mode === "auto" ? kind : state.mode) === mode;
              return (
                <button
                  key={mode}
                  type="button"
                  role="radio"
                  aria-checked={active}
                  data-testid={`add-source-mode-${mode}`}
                  onClick={() => onChange({ mode, probe: null })}
                  className={`flex h-7 items-center gap-1 rounded-[6px] px-2 text-[11px] font-medium transition-colors ${FOCUS_RING} ${
                    active
                      ? "bg-[var(--color-bg-hover)] text-[var(--color-text)]"
                      : "text-[var(--color-text-dim)] hover:text-[var(--color-text)]"
                  }`}
                >
                  {mode === "url" ? (
                    <Globe className="h-3 w-3" aria-hidden="true" />
                  ) : (
                    <Terminal className="h-3 w-3" aria-hidden="true" />
                  )}
                  {mode === "url" ? "Address" : "Command"}
                </button>
              );
            })}
          </div>
        </div>
        {input.kind === "invalid" ? (
          <p role="alert" className="text-[12px] leading-5 text-[var(--color-error)]">
            {input.reason}
          </p>
        ) : (
          <p className="text-[12px] leading-5 text-[var(--color-text-dim)]">
            Find it in the provider&apos;s docs under &ldquo;MCP&rdquo;. We work out the rest.
          </p>
        )}
      </div>

      {input.kind === "empty" && (
        <div className="flex flex-wrap items-center gap-1.5 text-[11.5px] text-[var(--color-text-dim)]">
          <span>Try</span>
          {EXAMPLES.map((example) => (
            <button
              key={example.value}
              type="button"
              onClick={() => onChange({ raw: example.value, mode: "auto", probe: null })}
              className={`rounded-[6px] border border-[var(--color-border)] bg-[var(--color-bg-card)] px-2 py-1 font-mono text-[11px] text-[var(--color-text-muted)] transition-colors hover:border-[var(--color-border-hover)] hover:text-[var(--color-text)] ${FOCUS_RING}`}
            >
              {example.label}
            </button>
          ))}
        </div>
      )}

      {input.kind === "command" && (
        <Notice
          tone="warning"
          testId="add-sandbox-warning"
          icon={<AlertTriangle className="h-3.5 w-3.5" aria-hidden="true" />}
        >
          <p className="font-medium">Runs inside your sandbox.</p>
          <p className="mt-0.5 text-[var(--color-text-muted)]">
            The agent can read this server&apos;s settings, including any keys.
          </p>
        </Notice>
      )}

      {state.probing && (
        <div
          role="status"
          data-testid="add-probing"
          className="flex items-center gap-3 rounded-[var(--radius-ctl)] border border-[var(--color-border)] bg-[var(--color-bg-card)] px-3.5 py-3"
        >
          <Loader2 className="h-4 w-4 animate-spin text-[var(--color-success)]" aria-hidden="true" />
          <div className="min-w-0">
            <p className="text-[12.5px] font-medium text-[var(--color-text)]">
              {input.kind === "command" ? "Starting the command…" : "Checking the address…"}
            </p>
            <p className="font-mono text-[11px] text-[var(--color-text-dim)]">
              {input.kind === "command"
                ? `${input.command} ${input.args.join(" ")}`.trim()
                : (input.kind === "url" && hostOf(input.url)) || ""}
              {input.kind === "command" ? " · installing, up to 90 s the first time" : " · asking what it offers"}
            </p>
          </div>
        </div>
      )}

      {failed && state.probe && (
        <Notice tone="error" testId="add-probe-error" icon={<AlertTriangle className="h-3.5 w-3.5" aria-hidden="true" />}>
          <p className="font-medium">{state.probe.error}</p>
          <p className="mt-0.5 text-[var(--color-text-muted)]">
            {input.kind === "command"
              ? "Check the package name and any arguments, then try again."
              : "Check the address, or ask the provider whether it needs a key."}
          </p>
          {/* "Try again" is the footer's primary button; only the alternative lives here. */}
          <div className="mt-2 flex flex-wrap items-center gap-2">
            <button
              type="button"
              onClick={onSaveAnyway}
              data-testid="add-probe-save-anyway"
              className={`rounded-[8px] border border-[var(--color-border)] bg-[var(--color-bg-card)] px-3 py-1.5 text-[12px] text-[var(--color-text)] hover:border-[var(--color-border-hover)] ${FOCUS_RING}`}
            >
              Save anyway
            </button>
            <span className="text-[11.5px] text-[var(--color-text-dim)]">and fix it from Settings later</span>
          </div>
        </Notice>
      )}
    </div>
  );
}
