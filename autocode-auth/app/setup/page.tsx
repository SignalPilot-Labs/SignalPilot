"use client";

import { useState, useEffect, useRef, useCallback } from "react";
import { useSession } from "next-auth/react";
import AuthLayout from "@/components/AuthLayout";

type Status = "waiting" | "connected" | "error";

interface SystemStatus {
  cli: Status;
  docker: Status;
  auth: Status;
  repo: string | null;
  mode: string | null;
}

const TERMINAL_LINES = [
  "$ signalpilot run --mode autonomous",
  "",
  "[run]  scanning codebase...",
  "[run]  3 priorities identified",
  '[run]  implementing: "add connection pooling to db layer"',
  "[run]  +47 -12 across 3 files",
  "[run]  tests passing (14/14)",
  "[run]  PR #1 opened → github.com/user/repo/pull/1",
  "",
  "✓ first improvement shipped in 4m 23s",
];

const FALLBACK_EMAIL = "";
const PLACEHOLDER_REPO = "github.com/user/repo";

function statusLabel(s: Status): string {
  if (s === "connected") return "CONNECTED ✓";
  if (s === "error") return "ERROR ✗";
  return "WAITING...";
}

function statusColor(s: Status): string {
  if (s === "connected") return "text-[var(--color-accent)]";
  if (s === "error") return "text-[var(--color-error)]";
  return "text-[var(--color-dim)]";
}

export default function SetupPage() {
  const { data: session } = useSession();
  const userEmail = session?.user?.email ?? FALLBACK_EMAIL;
  const [copied, setCopied] = useState(false);
  const [status, setStatus] = useState<SystemStatus>({
    cli: "waiting",
    docker: "waiting",
    auth: "waiting",
    repo: null,
    mode: null,
  });
  const [terminalLines, setTerminalLines] = useState<string[]>([]);
  const [runComplete, setRunComplete] = useState(false);
  const [showCursor, setShowCursor] = useState(true);
  const timeoutIds = useRef<ReturnType<typeof setTimeout>[]>([]);

  const schedule = useCallback((fn: () => void, ms: number) => {
    const id = setTimeout(fn, ms);
    timeoutIds.current.push(id);
  }, []);

  useEffect(() => {
    // Simulate CLI connecting and status updates
    schedule(() => setStatus((s) => ({ ...s, cli: "connected" })), 800);
    schedule(() => setStatus((s) => ({ ...s, docker: "connected" })), 1600);
    schedule(() => setStatus((s) => ({ ...s, auth: "connected" })), 2400);
    schedule(
      () =>
        setStatus((s) => ({
          ...s,
          repo: PLACEHOLDER_REPO,
          mode: "autonomous",
        })),
      3200
    );

    // Start streaming terminal lines after all statuses are green
    TERMINAL_LINES.forEach((line, i) => {
      schedule(() => {
        setTerminalLines((prev) => [...prev, line]);
        if (i === TERMINAL_LINES.length - 1) {
          setRunComplete(true);
          setShowCursor(false);
        }
      }, 3200 + (i + 1) * 300);
    });

    return () => {
      timeoutIds.current.forEach(clearTimeout);
    };
  }, [schedule]);

  const copyCommand = useCallback(() => {
    navigator.clipboard
      .writeText("npm install -g signalpilot-autocode")
      .then(() => {
        setCopied(true);
        schedule(() => setCopied(false), 2000);
      })
      .catch(() => {
        // Clipboard API unavailable
      });
  }, [schedule]);

  const allGreen =
    status.cli === "connected" &&
    status.docker === "connected" &&
    status.auth === "connected" &&
    status.repo !== null;

  return (
    <AuthLayout>
      <p className="text-[var(--color-dim)] text-xs tracking-[0.05em] mb-12">
        Already have an account?{" "}
        <a
          href="/signin"
          className="text-[var(--color-dim)] underline hover:text-[var(--color-accent)]"
        >
          Sign in
        </a>
      </p>

      <h1 className="text-[clamp(28px,5vw,40px)] font-bold uppercase tracking-[0.05em] mb-4">
        SETUP
      </h1>
      <p className="text-[var(--color-dim)] text-sm tracking-[0.05em] mb-16">
        Run the CLI. This page updates automatically.
      </p>

      {/* Install command */}
      <section className="mb-16" aria-labelledby="install-heading">
        <h2
          id="install-heading"
          className="text-xs text-[var(--color-dim)] tracking-[0.15em] uppercase mb-6"
        >
          INSTALL
        </h2>
        <div className="flex items-center justify-between border-2 border-[var(--color-border)] px-4 py-3 mb-4 overflow-x-auto">
          <code className="text-sm whitespace-nowrap font-mono">
            $ npm install -g signalpilot-autocode
          </code>
          <button
            onClick={copyCommand}
            className="text-xs text-[var(--color-dim)] hover:text-[var(--color-accent)] uppercase tracking-[0.1em] cursor-pointer ml-4 shrink-0"
          >
            [{copied ? "COPIED" : "COPY"}]
          </button>
        </div>
        <div className="border-2 border-[var(--color-border)] px-4 py-3 overflow-x-auto">
          <code className="text-sm whitespace-nowrap font-mono text-[var(--color-dim)]">
            $ signalpilot login
          </code>
        </div>
        <p className="text-[var(--color-dim)] text-xs tracking-[0.05em] mt-3">
          signalpilot login opens your browser for OAuth — then come back here.
        </p>
      </section>

      {/* Status indicators */}
      <section className="mb-8" aria-labelledby="status-heading">
        <h2
          id="status-heading"
          className="text-xs text-[var(--color-dim)] tracking-[0.15em] uppercase mb-6"
        >
          STATUS
        </h2>
        <div className="flex flex-col gap-2 font-mono text-sm">
          <div className="flex items-center gap-4">
            <span className="w-10 text-[var(--color-dim)]">[cli]</span>
            <span className={statusColor(status.cli)}>
              {statusLabel(status.cli)}
            </span>
          </div>
          <div className="flex items-center gap-4">
            <span className="w-10 text-[var(--color-dim)]">[docker]</span>
            <span className={statusColor(status.docker)}>
              {status.docker === "connected" ? "RUNNING ✓" : "CHECKING..."}
            </span>
          </div>
          <div className="flex items-center gap-4">
            <span className="w-10 text-[var(--color-dim)]">[auth]</span>
            <span className={statusColor(status.auth)}>
              {status.auth === "connected"
                ? `AUTHENTICATED as ${userEmail} ✓`
                : "PENDING..."}
            </span>
          </div>
          <div className="flex items-center gap-4">
            <span className="w-10 text-[var(--color-dim)]">[repo]</span>
            <span
              className={
                status.repo
                  ? "text-[var(--color-accent)]"
                  : "text-[var(--color-dim)]"
              }
            >
              {status.repo ? `${status.repo} ✓` : "NOT CONNECTED"}
            </span>
          </div>
          <div className="flex items-center gap-4">
            <span className="w-10 text-[var(--color-dim)]">[mode]</span>
            <span
              className={
                status.mode
                  ? "text-[var(--color-accent)]"
                  : "text-[var(--color-dim)]"
              }
            >
              {status.mode ? status.mode.toUpperCase() : "NOT SET"}
            </span>
          </div>
        </div>
      </section>

      {/* Terminal */}
      <section aria-labelledby="terminal-heading" className="mb-12">
        <h2
          id="terminal-heading"
          className="text-xs text-[var(--color-dim)] tracking-[0.15em] uppercase mb-4"
        >
          {allGreen ? "EXAMPLE OUTPUT" : "WAITING FOR CLI..."}
        </h2>
        <div
          role="log"
          aria-live="polite"
          aria-label="Terminal output"
          className="border-2 border-[var(--color-border)] bg-[var(--color-bg)] p-6 font-mono text-sm min-h-[280px]"
        >
          {!allGreen && (
            <div className="text-[var(--color-dim)]">
              <span>$ signalpilot status</span>
              <br />
              <br />
              {status.cli !== "connected" && (
                <span>waiting for cli connection...</span>
              )}
              {status.cli === "connected" && status.docker !== "connected" && (
                <span>checking docker...</span>
              )}
              {status.cli === "connected" &&
                status.docker === "connected" &&
                status.auth !== "connected" && (
                  <span>waiting for authentication...</span>
                )}
              {status.cli === "connected" &&
                status.docker === "connected" &&
                status.auth === "connected" &&
                !status.repo && <span>waiting for repo + mode...</span>}
            </div>
          )}

          {allGreen && (
            <>
              <div className="text-[var(--color-dim)] mb-4">
                <span>$ signalpilot status</span>
                <br />
                <br />
                <span className="text-[var(--color-accent)]">
                  [cli]     connected ✓
                  <br />
                  [docker]  running ✓
                  <br />
                  {`[auth]    authenticated as ${userEmail} ✓`}
                  <br />
                  {`[repo]    ${PLACEHOLDER_REPO} ✓`}
                  <br />
                  [mode]    autonomous
                  <br />
                  [agent]   starting first run...
                </span>
              </div>

              {terminalLines.length > 0 && (
                <div>
                  {terminalLines.map((line, i) => (
                    <span
                      key={i}
                      className={
                        line.startsWith("✓")
                          ? "text-[var(--color-accent)]"
                          : line.startsWith("[run]")
                          ? "text-white"
                          : "text-[var(--color-dim)]"
                      }
                    >
                      {line}
                      <br />
                    </span>
                  ))}
                </div>
              )}
            </>
          )}

          {showCursor && (
            <span
              className="text-[var(--color-accent)]"
              style={{ animation: "blink 1s step-end infinite" }}
              aria-hidden="true"
            >
              _
            </span>
          )}
        </div>
      </section>

      {/* Completion */}
      {runComplete && (
        <div className="flex flex-col sm:flex-row items-start sm:items-center gap-4 mb-8">
          <span className="text-sm font-bold uppercase tracking-[0.1em]">
            AUTOCODE IS RUNNING.
          </span>
          <a
            href="/dashboard"
            className="text-sm font-bold uppercase tracking-[0.1em] text-[var(--color-accent)] hover:text-[var(--color-text)]"
          >
            [OPEN DASHBOARD →]
          </a>
        </div>
      )}
    </AuthLayout>
  );
}
