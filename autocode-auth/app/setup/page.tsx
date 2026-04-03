// Bundle: ~8.1kb page JS (verified 2026-04-02)
"use client";

import { useState, useCallback, useRef, useEffect } from "react";
import AuthLayout from "@/components/AuthLayout";

type Mode = "autonomous" | "supervised" | "review" | null;

const GITHUB_REPO_RE = /^https:\/\/github\.com\/[\w.-]+\/[\w.-]+\/?$/;

const MODE_OPTIONS: { key: Mode; label: string; desc: string }[] = [
  { key: "autonomous", label: "AUTONOMOUS", desc: "Ships PRs without asking. You review after." },
  { key: "supervised", label: "SUPERVISED", desc: "Proposes PRs. You approve before merge." },
  { key: "review", label: "REVIEW ONLY", desc: "Analyzes and reports. Never touches code." },
];

function getTerminalLines(selectedMode: string) {
  return [
    `$ autocode run --mode ${selectedMode}`,
    "",
    "[CEO] scanning codebase...",
    "[CEO] 3 priorities identified",
    '[PM]  breaking down: "add connection pooling to db layer"',
    "[ENG] implementing on branch autocode/connection-pooling",
    "[ENG] +47 -12 across 3 files",
    "[ENG] tests passing (14/14)",
    "[ENG] PR #1 opened → github.com/user/repo/pull/1",
    "",
    "✓ first improvement shipped in 4m 23s",
  ];
}

export default function SetupPage() {
  const [step, setStep] = useState(1);
  const [copied, setCopied] = useState(false);
  const [repoUrl, setRepoUrl] = useState("");
  const [connecting, setConnecting] = useState(false);
  const [connected, setConnected] = useState(false);
  const [repoError, setRepoError] = useState("");
  const [mode, setMode] = useState<Mode>(null);
  const [terminalLines, setTerminalLines] = useState<string[]>([]);
  const [runComplete, setRunComplete] = useState(false);
  const [runStarted, setRunStarted] = useState(false);
  const timeoutIds = useRef<ReturnType<typeof setTimeout>[]>([]);
  const repoInputRef = useRef<HTMLInputElement>(null);
  const modeGroupRef = useRef<HTMLDivElement>(null);
  const startButtonRef = useRef<HTMLButtonElement>(null);

  useEffect(() => {
    return () => {
      timeoutIds.current.forEach(clearTimeout);
    };
  }, []);

  useEffect(() => {
    if (step === 2) repoInputRef.current?.focus();
    if (step === 3) modeGroupRef.current?.focus();
    if (step === 4) startButtonRef.current?.focus();
  }, [step]);

  const copyCommand = useCallback(() => {
    navigator.clipboard.writeText("npx signalpilot-autocode init").then(() => {
      setCopied(true);
      timeoutIds.current.push(setTimeout(() => setCopied(false), 2000));
    }).catch(() => {
      // Clipboard API unavailable — ignore silently
    });
  }, []);

  function handleConnect() {
    if (!GITHUB_REPO_RE.test(repoUrl.trim())) {
      setRepoError("ENTER A VALID GITHUB REPO URL");
      return;
    }
    setRepoError("");
    if (process.env.NODE_ENV !== "production") console.log("[setup] connecting repo", { url: repoUrl });
    setConnecting(true);
    // TODO: wire to backend — validate URL server-side before use
    timeoutIds.current.push(setTimeout(() => {
      setConnecting(false);
      setConnected(true);
      setStep(3);
    }, 1200));
  }

  function handleSelectMode(m: Mode) {
    if (process.env.NODE_ENV !== "production") console.log("[setup] mode selected", { mode: m });
    setMode(m);
    timeoutIds.current.push(setTimeout(() => setStep(4), 300));
  }

  function handleModeKeyDown(e: React.KeyboardEvent, index: number) {
    const radios = e.currentTarget.parentElement?.querySelectorAll<HTMLButtonElement>('[role="radio"]');
    if (!radios) return;
    let next = -1;
    if (e.key === "ArrowDown" || e.key === "ArrowRight") {
      next = (index + 1) % radios.length;
    } else if (e.key === "ArrowUp" || e.key === "ArrowLeft") {
      next = (index - 1 + radios.length) % radios.length;
    }
    if (next >= 0) {
      e.preventDefault();
      radios[next].focus();
    }
  }

  function handleStartRun() {
    if (runStarted || !mode) return;
    if (process.env.NODE_ENV !== "production") console.log("[setup] starting first run", { mode });
    setRunStarted(true);
    const lines = getTerminalLines(mode === "review" ? "review-only" : mode);
    lines.forEach((line, i) => {
      timeoutIds.current.push(setTimeout(() => {
        setTerminalLines((prev) => [...prev, line]);
        if (i === lines.length - 1) {
          setRunComplete(true);
        }
      }, (i + 1) * 400));
    });
  }

  function stepClass(s: number) {
    if (s < step) return "text-[var(--color-dim)]";
    if (s === step) return "";
    return "text-[var(--color-locked)] pointer-events-none";
  }

  function stepBorder(s: number) {
    if (s <= step) return "border-l-2 border-l-[var(--color-accent)] pl-6";
    return "border-l-2 border-l-[var(--color-locked)] pl-6";
  }

  return (
    <AuthLayout>
        {/* TODO: update href to /signin when that route exists */}
        <p className="text-[var(--color-dim)] text-xs tracking-[0.05em] mb-12">
          Already have an account?{" "}
          <a href="/signup" className="text-[var(--color-dim)] underline hover:text-[var(--color-accent)]">
            Sign in
          </a>
        </p>

        <h1 className="text-[clamp(28px,5vw,40px)] font-bold uppercase tracking-[0.05em] mb-24">
          SETUP
        </h1>

        {/* Step 1: Install CLI */}
        <section className={`${stepClass(1)} ${stepBorder(1)} mb-24`} aria-labelledby="step-1-heading">
          <p className="text-xs text-[var(--color-dim)] tracking-[0.15em] uppercase mb-2">
            {step > 1 && <span className="text-[var(--color-accent)]">✓ </span>}01
          </p>
          <h2 id="step-1-heading" className="text-lg font-bold uppercase tracking-[0.1em] mb-8">INSTALL CLI</h2>

          <div className="flex items-center justify-between border-2 border-[var(--color-border)] px-4 py-3 mb-4 overflow-x-auto">
            <code className="text-sm whitespace-nowrap">$ npx signalpilot-autocode init</code>
            <button
              onClick={copyCommand}
              className="text-xs text-[var(--color-dim)] hover:text-[var(--color-accent)] uppercase tracking-[0.1em] cursor-pointer ml-4 shrink-0"
            >
              [{copied ? "COPIED" : "COPY"}]
            </button>
          </div>

          <pre className="text-xs text-[var(--color-dim)] mb-8 leading-relaxed">{`✓ signalpilot-autocode installed
✓ config created at .signalpilot/config.yml
✓ ready to connect`}</pre>

          {step === 1 && (
            <button
              onClick={() => setStep(2)}
              className="border-2 border-[var(--color-accent)] bg-transparent text-[var(--color-text)] font-bold text-sm uppercase tracking-[0.1em] py-3 px-6 cursor-pointer hover:bg-[var(--color-accent)] hover:text-[var(--color-bg)]"
            >
              I&apos;VE RUN THIS
            </button>
          )}
        </section>

        {/* Step 2: Connect Repo */}
        <section className={`${stepClass(2)} ${stepBorder(2)} mb-24`} aria-labelledby="step-2-heading">
          <p className="text-xs text-[var(--color-dim)] tracking-[0.15em] uppercase mb-2">
            {step > 2 && <span className="text-[var(--color-accent)]">✓ </span>}02
          </p>
          <h2 id="step-2-heading" className="text-lg font-bold uppercase tracking-[0.1em] mb-8">CONNECT REPO</h2>

          <label htmlFor="repo-url" className="text-sm tracking-[0.05em] uppercase mb-4 block">PASTE YOUR GITHUB REPO URL</label>

          <input
            ref={repoInputRef}
            id="repo-url"
            type="url"
            value={repoUrl}
            onChange={(e) => { setRepoUrl(e.target.value); setRepoError(""); }}
            onKeyDown={(e) => e.key === "Enter" && handleConnect()}
            placeholder="https://github.com/user/repo"
            disabled={step !== 2}
            tabIndex={step !== 2 ? -1 : undefined}
            aria-describedby={repoError ? "repo-error" : undefined}
            className={`w-full bg-transparent border-0 border-b-2 border-[var(--color-border)] font-mono text-sm tracking-[0.05em] py-3 placeholder:text-[var(--color-dim)] focus-visible:border-[var(--color-accent)] outline-none focus-visible:outline-2 focus-visible:outline-[var(--color-accent)] focus-visible:outline-offset-2 mb-6 ${step === 2 ? "text-[var(--color-text)]" : ""}`}
          />

          {repoError && (
            <p id="repo-error" role="alert" className="text-[var(--color-error)] text-xs tracking-[0.1em] mt-[-16px] mb-4">{repoError}</p>
          )}

          {step === 2 && !connected && (
            <button
              onClick={handleConnect}
              disabled={connecting}
              className="border-2 border-[var(--color-accent)] bg-transparent text-[var(--color-text)] font-bold text-sm uppercase tracking-[0.1em] py-3 px-6 cursor-pointer hover:bg-[var(--color-accent)] hover:text-[var(--color-bg)] disabled:opacity-50 disabled:cursor-not-allowed"
            >
              {connecting ? "CONNECTING..." : "CONNECT"}
            </button>
          )}

          {connected && (
            <pre className="text-xs text-[var(--color-accent)] leading-relaxed mt-4">{`✓ connected to ${repoUrl.replace("https://", "")}
✓ 847 files indexed
✓ 23 improvement opportunities found`}</pre>
          )}
        </section>

        {/* Step 3: Select Mode */}
        <section className={`${stepClass(3)} ${stepBorder(3)} mb-24`} aria-labelledby="step-3-heading">
          <p className="text-xs text-[var(--color-dim)] tracking-[0.15em] uppercase mb-2">
            {step > 3 && <span className="text-[var(--color-accent)]">✓ </span>}03
          </p>
          <h2 id="step-3-heading" className="text-lg font-bold uppercase tracking-[0.1em] mb-8">SELECT MODE</h2>

          <div ref={modeGroupRef} className="flex flex-col gap-4" role="radiogroup" aria-labelledby="step-3-heading" tabIndex={step === 3 ? -1 : undefined}>
            {MODE_OPTIONS.map((option, index) => (
              <button
                key={option.key}
                role="radio"
                aria-checked={mode === option.key}
                tabIndex={step !== 3 ? -1 : index === 0 ? 0 : -1}
                onClick={() => step === 3 && handleSelectMode(option.key)}
                onKeyDown={(e) => handleModeKeyDown(e, index)}
                className={`w-full text-left p-4 border-2 cursor-pointer ${
                  mode === option.key
                    ? "bg-[var(--color-text)] text-[var(--color-bg)] border-[var(--color-border)] border-l-4 border-l-[var(--color-accent)]"
                    : "bg-transparent border-[var(--color-border)] hover:bg-[var(--color-text)] hover:text-[var(--color-bg)]"
                }`}
              >
                <p className="font-bold text-sm uppercase tracking-[0.1em]">{option.label}</p>
                <p className={`text-xs mt-1 ${mode === option.key ? "text-[var(--color-bg)]" : "text-[var(--color-dim)]"}`}>
                  {option.desc}
                </p>
              </button>
            ))}
          </div>
        </section>

        {/* Step 4: First Run */}
        <section className={`${stepClass(4)} ${stepBorder(4)} mb-24`} aria-labelledby="step-4-heading">
          <p className="text-xs text-[var(--color-dim)] tracking-[0.15em] uppercase mb-2">
            {runComplete && <span className="text-[var(--color-accent)]">✓ </span>}04
          </p>
          <h2 id="step-4-heading" className="text-lg font-bold uppercase tracking-[0.1em] mb-8">FIRST RUN</h2>

          {!runStarted && step === 4 && (
            <button
              ref={startButtonRef}
              onClick={handleStartRun}
              className="w-full border-2 border-[var(--color-accent)] bg-transparent text-[var(--color-text)] font-bold text-sm uppercase tracking-[0.1em] py-5 px-6 cursor-pointer hover:bg-[var(--color-accent)] hover:text-[var(--color-bg)]"
            >
              START AUTOCODE
            </button>
          )}

          {runStarted && (
            <pre className="text-sm leading-loose text-[var(--color-text)]" aria-live="polite" role="log">
              {terminalLines.map((line, i) => (
                <span key={i} className={line.startsWith("✓") ? "text-[var(--color-accent)]" : ""}>
                  {line}
                  {"\n"}
                </span>
              ))}
            </pre>
          )}

          {runComplete && (
            <div className="mt-8 flex flex-col sm:flex-row items-start sm:items-center gap-4">
              <span className="text-sm font-bold uppercase tracking-[0.1em]">AUTOCODE IS RUNNING.</span>
              {/* TODO: update href to /dashboard when that route exists */}
              <a
                href="/dashboard"
                className="text-sm font-bold uppercase tracking-[0.1em] text-[var(--color-accent)] hover:text-[var(--color-text)]"
              >
                [OPEN DASHBOARD <span aria-hidden="true">→</span>]
              </a>
            </div>
          )}
        </section>
    </AuthLayout>
  );
}
