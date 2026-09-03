"use client";

import { ChatCode, CopyButton } from "~/components/chat/chat-code";
import type { RunStep, TerminalResult } from "~/lib/chat-run-steps";
import { registerToolCard, type ToolCardContext, type ToolCardSummary } from "../registry";
import { iconForKind } from "../registry-tools";

/**
 * Terminal card: `sandbox_exec` and claude-code `Bash`. A prompt line with a
 * blinking cursor while running; the full command, stdout, stderr (error
 * tint) and the exit code once done.
 */

/** Characters of the command shown in the compact chip stat. */
const COMMAND_MAX = 48;

function terminalResult(step: RunStep): TerminalResult | null {
  return step.result?.kind === "terminal" ? step.result : null;
}

export function terminalCommand(step: RunStep): string {
  const result = terminalResult(step);
  const raw =
    result?.command ??
    (typeof step.input?.command === "string" ? step.input.command : null) ??
    step.code ??
    "";
  return raw.trim();
}

function lineCount(text: string): number {
  const trimmed = text.replace(/\n+$/, "");
  return trimmed ? trimmed.split("\n").length : 0;
}

function exitOk(result: TerminalResult | null): boolean {
  return !result || result.exitCode === 0 || result.exitCode === null;
}

/** The command clipped for the chip: `$ python analysis/q3_growth.py --check`. */
export function shortCommand(step: RunStep): string {
  const command = terminalCommand(step);
  const short = command.length > COMMAND_MAX ? `${command.slice(0, COMMAND_MAX)}…` : command;
  return `$ ${short || "command"}`;
}

export function summarizeTerminal(step: RunStep): ToolCardSummary {
  const title = step.title;
  const failed = step.status === "failed";
  const result = terminalResult(step);
  const parts = [shortCommand(step)];
  if (!result) return { title, stat: parts.join(" · "), ok: !failed };
  if (result.exitCode != null) parts.push(`exit ${result.exitCode}`);
  return { title, stat: parts.join(" · "), ok: !failed && exitOk(result) };
}

function PromptLine({ command, cursor }: { command: string; cursor: boolean }) {
  return (
    <div className="whitespace-pre-wrap break-all px-3.5 py-2.5 font-mono text-[11.5px] text-[var(--color-text)]">
      <span className="mr-1.5 text-[var(--color-text-dim)]">$</span>
      {command}
      {cursor && (
        <span
          aria-hidden
          className="chat-tool-cursor-blink ml-0.5 inline-block h-[1.1em] w-[0.55em] translate-y-[3px] bg-[var(--color-success)]/80 align-baseline"
        />
      )}
    </div>
  );
}

export function TerminalRunning({ step }: ToolCardContext) {
  return (
    <div data-testid="chat-terminal-card">
      <PromptLine command={terminalCommand(step)} cursor />
    </div>
  );
}

function ExitPill({ code }: { code: number }) {
  const ok = code === 0;
  return (
    <span
      data-testid="chat-terminal-exit"
      className={`inline-flex items-center rounded-md border px-1.5 py-0.5 font-mono text-[10px] tabular-nums ${
        ok
          ? "border-[var(--color-border)] text-[var(--color-text-muted)]"
          : "border-[var(--color-error)]/40 bg-[rgba(255,68,68,0.06)] text-[var(--color-error)]"
      }`}
    >
      exit {code}
    </span>
  );
}

function Stream({
  label,
  text,
  truncated,
  tone,
}: {
  label: string;
  text: string;
  truncated: boolean;
  tone: "stdout" | "stderr";
}) {
  const error = tone === "stderr";
  return (
    <div
      data-testid={`chat-terminal-${tone}`}
      className={`border-t ${
        error
          ? "border-[var(--color-error)]/25 bg-[rgba(255,68,68,0.04)]"
          : "border-[var(--color-border)]"
      }`}
    >
      <div className="flex items-center px-3.5 pt-1.5 text-[10px] uppercase tracking-[0.14em] text-[var(--color-text-dim)]">
        <span className={error ? "text-[var(--color-error)]/80" : undefined}>{label}</span>
        {truncated && <span className="ml-2 normal-case tracking-normal">truncated</span>}
        <span className="ml-auto">
          <CopyButton text={text} />
        </span>
      </div>
      <pre
        className={`max-h-64 overflow-auto whitespace-pre-wrap break-words px-3.5 pb-3 pt-1 font-mono text-[11.5px] leading-[1.6] ${
          error ? "text-[var(--color-error)]/90" : "text-[var(--color-text-muted)]"
        }`}
      >
        {text.replace(/\n+$/, "")}
      </pre>
    </div>
  );
}

export function TerminalExpanded({ step }: ToolCardContext) {
  const result = terminalResult(step);
  const command = terminalCommand(step);
  if (!result) {
    // Legacy completion: only the command is known.
    return (
      <div data-testid="chat-terminal-card">
        {command ? <ChatCode code={command} language="bash" maxHeightClass="max-h-48" /> : null}
      </div>
    );
  }
  return (
    <div data-testid="chat-terminal-card">
      {command && <ChatCode code={command} language="bash" maxHeightClass="max-h-48" />}
      {result.stdout.trim() && (
        <Stream label="stdout" text={result.stdout} truncated={result.stdoutTruncated} tone="stdout" />
      )}
      {result.stderr.trim() && (
        <Stream label="stderr" text={result.stderr} truncated={result.stderrTruncated} tone="stderr" />
      )}
      {result.exitCode != null && (
        <div className="flex items-center gap-2 border-t border-[var(--color-border)] px-3.5 py-1.5">
          <ExitPill code={result.exitCode} />
          {lineCount(result.stdout) > 0 ? (
            <span className="text-[10px] text-[var(--color-text-dim)]">
              {lineCount(result.stdout)} {lineCount(result.stdout) === 1 ? "line" : "lines"}
            </span>
          ) : (
            !result.stderr.trim() && (
              <span className="text-[10px] text-[var(--color-text-dim)]">no output</span>
            )
          )}
        </div>
      )}
    </div>
  );
}

registerToolCard({
  kind: "terminal",
  Icon: iconForKind("terminal"),
  accent: "shell",
  summarize: summarizeTerminal,
  Running: TerminalRunning,
  Expanded: TerminalExpanded,
});
