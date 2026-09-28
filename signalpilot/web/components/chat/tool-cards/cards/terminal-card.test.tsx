import { act } from "react";
import { openToolRow } from "../test-utils";
import { createRoot, type Root } from "react-dom/client";
import { afterEach, beforeEach, describe, expect, it } from "vitest";
import type { RunStep, TerminalResult } from "~/lib/chat-run-steps";
import { ToolCard } from "../tool-card";
import { probeCaption, summarizeTerminal } from "./terminal-card";

(
  globalThis as typeof globalThis & { IS_REACT_ACT_ENVIRONMENT: boolean }
).IS_REACT_ACT_ENVIRONMENT = true;

const COMMAND = "python analysis/q3_growth.py --check";
const STDOUT =
  '[\n  {"region": "APAC", "growth_pct": 31.5}\n]\ncheck: 3 regions, growth sums to 51.9';

const LEGACY = {
  kind: "legacy",
  summary: null,
  resultText: null,
  resultChars: null,
  truncated: false,
  errorMessage: null,
} as const;

const terminal = (overrides: Partial<TerminalResult> = {}): TerminalResult => ({
  kind: "terminal",
  summary: `${COMMAND} · exit 0`,
  resultText: STDOUT,
  resultChars: STDOUT.length,
  truncated: false,
  errorMessage: null,
  command: COMMAND,
  exitCode: 0,
  stdout: STDOUT,
  stderr: "",
  stdoutTruncated: false,
  stderrTruncated: false,
  probe: false,
  ...overrides,
});

const probe = (command: string, exitCode = 1): TerminalResult =>
  terminal({
    command,
    exitCode,
    stdout: "",
    stderr: exitCode === 1 ? "ls: cannot access 'x': No such file or directory" : "",
    probe: true,
  });

function step(overrides: Partial<RunStep> = {}): RunStep {
  return {
    key: "t7",
    sequence: 7,
    category: "terminal",
    status: "succeeded",
    title: "Ran a command",
    tool: "Bash",
    toolOrigin: "claude-code",
    input: { command: COMMAND },
    sql: null,
    code: null,
    file: null,
    sources: [],
    detail: null,
    result: null,
    startedAt: "2026-09-01T12:00:00.000Z",
    endedAt: "2026-09-01T12:00:01.200Z",
    durationMs: 1_200,
    children: [],
    subagentType: null,
    report: null,
    liveText: "",
    ...overrides,
  };
}

const q = (root: ParentNode, selector: string) => root.querySelector(selector);

describe("summarizeTerminal", () => {
  it("keeps the humanized title and puts the command and exit code in the stat", () => {
    expect(summarizeTerminal(step({ result: terminal() }))).toEqual({
      title: "Ran a command",
      stat: `$ ${COMMAND} · exit 0`,
      ok: true,
    });
    expect(summarizeTerminal(step()).stat).toBe(`$ ${COMMAND}`);
  });
  it("clips long commands to 48 characters", () => {
    const long = "x".repeat(80);
    expect(summarizeTerminal(step({ input: { command: long } })).stat).toBe(
      `$ ${"x".repeat(48)}…`,
    );
  });
  it("marks non-zero exits as not ok", () => {
    expect(summarizeTerminal(step({ result: terminal({ exitCode: 2, stdout: "" }) }))).toMatchObject(
      { stat: `$ ${COMMAND} · exit 2`, ok: false },
    );
    expect(summarizeTerminal(step({ status: "failed" })).ok).toBe(false);
  });
  it("words a probe by exit code and command head, and keeps it ok", () => {
    const caption = (command: string, code = 1) =>
      probeCaption(step({ input: { command }, result: probe(command, code) }));
    expect(caption("ls analysis/cache")).toBe("not found");
    expect(caption("cat notes.md")).toBe("not found");
    expect(caption("/usr/bin/stat out.csv")).toBe("not found");
    expect(caption("grep -rn region models/")).toBe("no match");
    expect(caption("find . -name '*.sql'")).toBe("no match");
    expect(caption("test -f dbt_project.yml")).toBe("false");
    expect(caption("[ -d target ]")).toBe("false");
    expect(caption("python probe.py")).toBe("exit 1");
    expect(caption("grep -rn region models/", 2)).toBe("exit 2");
    expect(probeCaption(step({ result: terminal({ exitCode: 1 }) }))).toBeNull();
    expect(summarizeTerminal(step({ input: { command: "ls x" }, result: probe("ls x") }))).toEqual({
      title: "Ran a command",
      stat: "$ ls x · not found",
      ok: true,
    });
  });
});

describe("terminal card", () => {
  let container: HTMLDivElement;
  let root: Root;
  beforeEach(() => {
    container = document.createElement("div");
    document.body.appendChild(container);
    root = createRoot(container);
  });
  afterEach(async () => {
    await act(async () => root.unmount());
    container.remove();
  });
  const render = async (s: RunStep) => {
    await act(async () => {
      root.render(
        <ol>
          <ToolCard step={s} groupLive isLastInGroup />
        </ol>,
      );
    });
  };

  it("shows the prompt with a blinking cursor while running", async () => {
    await render(step({ status: "running", endedAt: null, durationMs: null }));
    await openToolRow(container);
    const body = q(container, '[data-testid="chat-terminal-card"]');
    expect(body?.textContent).toContain(`$${COMMAND}`);
    expect(q(body!, ".chat-tool-cursor-blink")).not.toBeNull();
  });

  it("compacts a clean run to a chip and expands to stdout with the exit pill", async () => {
    await render(step({ result: terminal() }));
    const chip = q(container, '[data-testid="chat-tool-chip"]') as HTMLButtonElement;
    expect(chip.textContent).toContain("Ran a command");
    expect(chip.textContent).toContain(`$ ${COMMAND} · exit 0`);
    expect(chip.textContent).not.toContain("lines");
    await act(async () => chip.click());
    expect(q(container, '[data-testid="chat-terminal-stdout"]')?.textContent).toContain(
      "growth sums to 51.9",
    );
    expect(q(container, '[data-testid="chat-terminal-card"]')?.textContent).toContain("4 lines");
    expect(q(container, '[data-testid="chat-terminal-stderr"]')).toBeNull();
    expect(q(container, '[data-testid="chat-terminal-exit"]')?.textContent).toBe("exit 0");
    expect(
      q(container, '[data-testid="chat-terminal-stdout"] button[aria-label="Copy"]'),
    ).not.toBeNull();
  });

  it("keeps a failing command open with stderr and the truncation note", async () => {
    await render(
      step({
        status: "failed",
        detail: "Traceback: KeyError 'region'",
        result: terminal({
          exitCode: 1,
          stdout: "",
          stderr: "Traceback (most recent call last)\nKeyError: 'region'",
          stderrTruncated: true,
          errorMessage: "KeyError 'region'",
        }),
      }),
    );
    await openToolRow(container);
    expect(q(container, '[data-testid="chat-tool-card"]')?.getAttribute("data-density")).toBe(
      "expanded",
    );
    const stderr = q(container, '[data-testid="chat-terminal-stderr"]');
    expect(stderr?.textContent).toContain("KeyError");
    expect(stderr?.textContent).toContain("truncated");
    const exit = q(container, '[data-testid="chat-terminal-exit"]');
    expect(exit?.textContent).toBe("exit 1");
    expect(exit?.className).toContain("text-[var(--color-warning)]");
    expect(container.innerHTML).not.toContain("color-error");
  });

  it("renders a probe as a completed call with a muted caption", async () => {
    const command = "grep -rn region_name models/";
    await render(step({ input: { command }, result: probe(command) }));
    const chip = q(container, '[data-testid="chat-tool-chip"]') as HTMLButtonElement;
    expect(chip.getAttribute("data-ok")).toBe("true");
    expect(chip.textContent).toContain("no match");
    expect(chip.textContent).not.toContain("exit 1");
    expect(q(container, '[data-testid="chat-tool-chip-failed"]')).toBeNull();
    await act(async () => chip.click());
    expect(q(container, '[data-testid="chat-tool-failed-badge"]')).toBeNull();
    expect(q(container, '[data-testid="chat-tool-error"]')).toBeNull();
    const probeCaptionEl = q(container, '[data-testid="chat-terminal-probe"]');
    expect(probeCaptionEl?.textContent).toBe("no match");
    expect(probeCaptionEl?.className).toContain("color-text-muted");
    const exit = q(container, '[data-testid="chat-terminal-exit"]');
    expect(exit?.textContent).toBe("exit 1");
    expect(exit?.className).not.toContain("color-warning");
    expect(container.innerHTML).not.toContain("color-warning");
    expect(container.innerHTML).not.toContain("color-error");
  });

  it("degrades a legacy completion to the command block", async () => {
    await render(step({ result: LEGACY }));
    const chip = q(container, '[data-testid="chat-tool-chip"]') as HTMLButtonElement;
    expect(chip.textContent).toContain("Ran a command");
    expect(chip.textContent).toContain("$ python");
    await act(async () => chip.click());
    expect(q(container, '[data-testid="chat-terminal-stdout"]')).toBeNull();
    expect(q(container, '[data-testid="chat-terminal-card"] pre')?.textContent).toContain(COMMAND);
  });
});
