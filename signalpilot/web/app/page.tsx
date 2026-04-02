"use client";

import { useEffect, useState, useRef } from "react";
import { useRouter } from "next/navigation";

/**
 * Landing / boot sequence page.
 * Shows a brief terminal-style boot animation then redirects to dashboard.
 * Gives the product a strong first impression — "infra that takes itself seriously."
 */

const BOOT_LINES: { text: string; delay: number; color: string; check?: boolean; success?: boolean }[] = [
  { text: "signalpilot v0.1.0", delay: 0, color: "text-[var(--color-text)]" },
  { text: "initializing governance engine...", delay: 200, color: "text-[var(--color-text-dim)]" },
  { text: "├── sql_parse", delay: 400, color: "text-[var(--color-text-dim)]", check: true },
  { text: "├── policy_check", delay: 550, color: "text-[var(--color-text-dim)]", check: true },
  { text: "├── cost_estimate", delay: 700, color: "text-[var(--color-text-dim)]", check: true },
  { text: "├── row_limit", delay: 850, color: "text-[var(--color-text-dim)]", check: true },
  { text: "├── pii_redact", delay: 1000, color: "text-[var(--color-text-dim)]", check: true },
  { text: "└── audit_log", delay: 1150, color: "text-[var(--color-text-dim)]", check: true },
  { text: "firecracker sandbox: connected", delay: 1400, color: "text-[var(--color-success)]", success: true },
  { text: "kvm acceleration: available", delay: 1550, color: "text-[var(--color-success)]", success: true },
  { text: "mcp server: listening on :3300", delay: 1700, color: "text-[var(--color-success)]", success: true },
  { text: "", delay: 1850, color: "" },
  { text: "ready. redirecting to dashboard...", delay: 1950, color: "text-[var(--color-text-muted)]" },
];

/* ── Animated progress bar ── */
function ProgressBar({ progress }: { progress: number }) {
  return (
    <div className="flex items-center gap-2">
      <div className="flex-1 h-[2px] bg-[var(--color-border)] overflow-hidden">
        <div
          className="h-full bg-[var(--color-success)] transition-all duration-200 ease-out"
          style={{ width: `${progress}%` }}
        />
      </div>
      <span className="text-[9px] text-[var(--color-text-dim)] tabular-nums w-8 text-right">
        {Math.round(progress)}%
      </span>
    </div>
  );
}

/* ── Particle grid background ── */
function ParticleGrid() {
  return (
    <div className="absolute inset-0 pointer-events-none overflow-hidden" aria-hidden="true">
      {/* Grid pattern */}
      <svg width="100%" height="100%" className="opacity-[0.025]">
        <defs>
          <pattern id="boot-grid" width="32" height="32" patternUnits="userSpaceOnUse">
            <path d="M32 0V32M0 32H32" stroke="currentColor" strokeWidth="0.5" fill="none" />
          </pattern>
          <radialGradient id="boot-fade" cx="50%" cy="50%" r="35%">
            <stop offset="0%" stopColor="white" stopOpacity="1" />
            <stop offset="100%" stopColor="white" stopOpacity="0" />
          </radialGradient>
          <mask id="boot-mask">
            <rect width="100%" height="100%" fill="url(#boot-fade)" />
          </mask>
        </defs>
        <rect width="100%" height="100%" fill="url(#boot-grid)" mask="url(#boot-mask)" />
      </svg>

      {/* Subtle green glow behind terminal */}
      <div
        className="absolute top-1/2 left-1/2 -translate-x-1/2 -translate-y-1/2 w-[500px] h-[500px] rounded-full blur-[150px]"
        style={{ background: "radial-gradient(circle, rgba(0,255,136,0.03) 0%, transparent 70%)" }}
      />

      {/* Scanline effect */}
      <div className="absolute inset-0 opacity-[0.015]" style={{
        backgroundImage: "repeating-linear-gradient(0deg, transparent, transparent 1px, rgba(255,255,255,0.03) 1px, rgba(255,255,255,0.03) 2px)",
        backgroundSize: "100% 2px",
      }} />
    </div>
  );
}

export default function Home() {
  const router = useRouter();
  const [visibleLines, setVisibleLines] = useState<number>(0);
  const [showCursor, setShowCursor] = useState(true);
  const [progress, setProgress] = useState(0);
  const containerRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    // Show each line after its delay
    const timers = BOOT_LINES.map((line, i) =>
      setTimeout(() => {
        setVisibleLines(i + 1);
        setProgress(((i + 1) / BOOT_LINES.length) * 100);
      }, line.delay)
    );

    // Redirect after boot sequence
    const redirect = setTimeout(() => {
      router.push("/dashboard");
    }, 3200);

    // Cursor blink
    const cursorInterval = setInterval(() => {
      setShowCursor((prev) => !prev);
    }, 530);

    return () => {
      timers.forEach(clearTimeout);
      clearTimeout(redirect);
      clearInterval(cursorInterval);
    };
  }, [router]);

  return (
    <div ref={containerRef} className="flex items-center justify-center min-h-screen -ml-56 relative">
      <ParticleGrid />

      <div className="w-[560px] relative z-10">
        {/* Terminal window */}
        <div className="border border-[var(--color-border)] bg-[var(--color-bg-card)] shadow-[0_0_80px_-20px_rgba(0,255,136,0.08)]">
          {/* Title bar */}
          <div className="flex items-center gap-3 px-4 py-2.5 border-b border-[var(--color-border)] bg-[var(--color-bg-elevated)]">
            <div className="flex items-center gap-1.5">
              <span className="w-[7px] h-[7px] rounded-full bg-[#ff5f57] opacity-60" />
              <span className="w-[7px] h-[7px] rounded-full bg-[#febc2e] opacity-60" />
              <span className="w-[7px] h-[7px] rounded-full bg-[#28c840] opacity-60" />
            </div>
            <code className="text-[10px] text-[var(--color-text-dim)] tracking-wider flex-1 text-center">
              signalpilot — boot
            </code>
            <div className="w-[46px]" /> {/* Balance the dots */}
          </div>

          {/* Terminal body */}
          <div className="p-5 font-mono min-h-[360px]">
            {/* Logo */}
            <div className="mb-6">
              <svg width="220" height="36" viewBox="0 0 220 36" fill="none" className="mb-4">
                {/* Terminal frame with draw-in effect */}
                <rect x="0.5" y="0.5" width="33" height="33" stroke="#e8e8e8" strokeWidth="1" fill="none">
                  <animate attributeName="stroke-dasharray" from="0 136" to="136 0" dur="0.6s" fill="freeze" />
                </rect>
                <rect x="4" y="4" width="26" height="26" fill="#050505" />
                {/* Chevron prompt */}
                <path d="M10 12L17 17L10 22" stroke="#e8e8e8" strokeWidth="1.5" strokeLinecap="square" />
                {/* Cursor line */}
                <line x1="19" y1="22" x2="26" y2="22" stroke="#e8e8e8" strokeWidth="1.5" strokeLinecap="square" />
                {/* Signal dot with pulse */}
                <circle cx="26" cy="8" r="4" fill="#00ff88" opacity="0">
                  <animate attributeName="r" values="2;6;2" dur="2s" begin="0.8s" repeatCount="indefinite" />
                  <animate attributeName="opacity" values="0;0.15;0" dur="2s" begin="0.8s" repeatCount="indefinite" />
                </circle>
                <circle cx="26" cy="8" r="2" fill="#00ff88">
                  <animate attributeName="opacity" from="0" to="1" dur="0.3s" begin="0.5s" fill="freeze" />
                </circle>
                {/* Text */}
                <text x="44" y="16" fill="#e8e8e8" fontSize="12" fontFamily="monospace" letterSpacing="0.12em" fontWeight="600">
                  SIGNALPILOT
                </text>
                <text x="44" y="28" fill="#444444" fontSize="9" fontFamily="monospace" letterSpacing="0.15em">
                  governed sandbox console
                </text>
              </svg>
              <div className="w-full h-px bg-gradient-to-r from-transparent via-[var(--color-border)] to-transparent" />
            </div>

            {/* Boot lines */}
            <div className="space-y-[6px]">
              {BOOT_LINES.slice(0, visibleLines).map((line, i) => (
                <div key={i} className="flex items-center gap-2 animate-fade-in">
                  {line.text === "" ? (
                    <div className="h-3" />
                  ) : (
                    <>
                      <span className="text-[10px] text-[var(--color-text-dim)] w-6 text-right tabular-nums select-none opacity-40">
                        {String(i + 1).padStart(2, "0")}
                      </span>
                      <code className={`text-[11px] tracking-wider ${line.color} flex items-center gap-2`}>
                        {line.success && (
                          <span className="w-1 h-1 bg-[var(--color-success)] flex-shrink-0" />
                        )}
                        <span>{line.text}</span>
                        {line.check && (
                          <svg width="10" height="10" viewBox="0 0 10 10" fill="none" className="flex-shrink-0">
                            <path d="M2 5L4 7L8 3" stroke="var(--color-success)" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round" />
                          </svg>
                        )}
                      </code>
                    </>
                  )}
                </div>
              ))}
            </div>

            {/* Cursor */}
            {visibleLines < BOOT_LINES.length && (
              <div className="flex items-center gap-2 mt-1">
                <span className="text-[10px] text-[var(--color-text-dim)] w-6 text-right tabular-nums select-none opacity-40">
                  {String(visibleLines + 1).padStart(2, "0")}
                </span>
                <span className={`text-[11px] text-[var(--color-success)] ${showCursor ? "opacity-100" : "opacity-0"}`}>
                  ▊
                </span>
              </div>
            )}
          </div>

          {/* Progress bar */}
          <div className="px-5 pb-2">
            <ProgressBar progress={progress} />
          </div>

          {/* Status bar */}
          <div className="px-4 py-2 border-t border-[var(--color-border)] flex items-center justify-between bg-[var(--color-bg-elevated)]">
            <div className="flex items-center gap-3">
              <span className="flex items-center gap-1.5 text-[9px] text-[var(--color-text-dim)] tracking-wider">
                <span className="relative flex h-1.5 w-1.5">
                  {progress >= 100 && (
                    <span className="animate-ping absolute inline-flex h-full w-full bg-[var(--color-success)] opacity-30" />
                  )}
                  <span className={`relative inline-flex h-1.5 w-1.5 ${progress >= 100 ? "bg-[var(--color-success)]" : "bg-[var(--color-text-dim)]"} transition-colors`} />
                </span>
                {progress >= 100 ? "system ready" : "booting..."}
              </span>
            </div>
            <div className="flex items-center gap-3">
              <span className="text-[9px] text-[var(--color-text-dim)] tracking-wider">
                pid 1
              </span>
              <span className="w-px h-3 bg-[var(--color-border)]" />
              <span className="text-[9px] text-[var(--color-text-dim)] tracking-wider tabular-nums">
                v0.1.0
              </span>
            </div>
          </div>
        </div>

        {/* Skip link */}
        <div className="mt-4 text-center">
          <button
            onClick={() => router.push("/dashboard")}
            className="text-[10px] text-[var(--color-text-dim)] hover:text-[var(--color-text)] transition-colors tracking-wider group"
          >
            skip <span className="group-hover:translate-x-0.5 inline-block transition-transform">&rarr;</span> dashboard
          </button>
        </div>
      </div>
    </div>
  );
}
