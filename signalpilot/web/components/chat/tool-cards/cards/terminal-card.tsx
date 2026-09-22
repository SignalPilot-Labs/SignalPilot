"use client";

import { ChatCode, CopyButton } from "~/components/chat/chat-code";
import type { RunStep, TerminalResult } from "~/lib/chat-run-steps";
import { registerToolCard, type ToolCardContext, type ToolCardSummary } from "../registry";
import { iconForKind } from "../registry-tools";

/**
 * Terminal card: `sandbox_exec` and claude-code `Bash`. A prompt line with a
 * blinking cursor while running; the full command, stdout, stderr (error
 * tint) and the exit code once done. A probe (`result.probe`, a non-zero
 * exit from ls/grep/test that only asked a question) renders as a completed
 * call with a muted "not found" / "no match" caption instead of a failure.
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
  return !result || result.probe || result.exitCode === 0 || result.exitCode === null;
}

const PROBE_NOT_FOUND = new Set(["ls", "cat", "stat"]);
const PROBE_NO_MATCH = new Set(["grep", "find"]);
const PROBE_FALSE = new Set(["test", "["]);

/** First token of the command, without a leading path (`/usr/bin/grep`). */
function commandHead(command: string): string {
  const head = command.split(/\s+/)[0] ?? "";
  return head.slice(head.lastIndexOf("/") + 1);
}

/**
 * The muted caption for a probe: "not found" for exit 1 from ls/cat/stat,
 * "no match" from grep/find, "false" from test/[, otherwise "exit N".
 * Null when the result is not a probe.
 */
export function probeCaption(step: RunStep): string | null {
  const result = terminalResult(step);
  if (!result?.probe) return null;
  const code = result.exitCode;
  if (code == null) return "no result";
  if (code === 1) {
    const head = commandHead(terminalCommand(step));
    if (PROBE_NOT_FOUND.has(head)) return "not found";
    if (PROBE_NO_MATCH.has(head)) return "no match";
    if (PROBE_FALSE.has(head)) return "false";
  }
  return `exit ${code}`;
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
  const caption = probeCaption(step);
  if (caption) parts.push(caption);
  else if (result.exitCode != null) parts.push(`exit ${result.exitCode}`);
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

function ExitPill({ code, neutral = false }: { code: number; neutral?: boolean }) {
  const ok = neutral || code === 0;
  return (
    <span
      data-testid="chat-terminal-exit"
      className={`inline-flex items-center rounded-md border px-1.5 py-0.5 font-mono text-[10px] tabular-nums ${
        ok
          ? "border-[var(--color-border)] text-[var(--color-text-muted)]"
          : "border-[var(--color-warning)]/40 bg-[rgba(255,170,0,0.06)] text-[var(--color-warning)]"
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
  neutral = false,
}: {
  label: string;
  text: string;
  truncated: boolean;
  tone: "stdout" | "stderr";
  /** Drop the stderr tint (a probe's "No such file" line is not an error). */
  neutral?: boolean;
}) {
  const error = tone === "stderr" && !neutral;
  return (
    <div
      data-testid={`chat-terminal-${tone}`}
      className="border-t border-[var(--color-border)]"
    >
      <div className="flex items-center px-3.5 pt-1.5 text-[10px] uppercase tracking-[0.14em] text-[var(--color-text-dim)]">
        <span className={error ? "text-[var(--color-warning)]/80" : undefined}>{label}</span>
        {truncated && <span className="ml-2 normal-case tracking-normal">truncated</span>}
        <span className="ml-auto">
          <CopyButton text={text} />
        </span>
      </div>
      <pre className="max-h-64 overflow-auto whitespace-pre-wrap break-words px-3.5 pb-3 pt-1 font-mono text-[11.5px] leading-[1.6] text-[var(--color-text-muted)]">
        {text.replace(/\n+$/, "")}
      </pre>
    </div>
  );
}

export function TerminalExpanded({ step }: ToolCardContext) {
  const result = terminalResult(step);
  const command = terminalCommand(step);
  const caption = probeCaption(step);
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
        <Stream
          label="stderr"
          text={result.stderr}
          truncated={result.stderrTruncated}
          tone="stderr"
          neutral={caption !== null}
        />
      )}
      {result.exitCode != null && (
        <div className="flex items-center gap-2 border-t border-[var(--color-border)] px-3.5 py-1.5">
          <ExitPill code={result.exitCode} neutral={caption !== null} />
          {caption && (
            <span
              data-testid="chat-terminal-probe"
              className="text-[10px] text-[var(--color-text-muted)]"
            >
              {caption}
            </span>
          )}
          {lineCount(result.stdout) > 0 ? (
            <span className="text-[10px] text-[var(--color-text-dim)]">
              {lineCount(result.stdout)} {lineCount(result.stdout) === 1 ? "line" : "lines"}
            </span>
          ) : (
            !result.stderr.trim() &&
            !caption && (
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
