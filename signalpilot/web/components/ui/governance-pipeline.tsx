"use client";

import { useState, useEffect } from "react";

interface PipelineStep {
  id: string;
  label: string;
  shortLabel: string;
  description: string;
  detail: string;
  icon: React.ReactNode;
}

/* ── Minimal geometric icons for each pipeline stage ── */
function ParseIcon() {
  return (
    <svg width="16" height="16" viewBox="0 0 16 16" fill="none">
      <path d="M3 4H13M3 8H9M3 12H11" stroke="currentColor" strokeWidth="1" strokeLinecap="square" />
      <rect x="11" y="6" width="4" height="4" stroke="currentColor" strokeWidth="0.75" fill="none" />
    </svg>
  );
}
function PolicyIcon() {
  return (
    <svg width="16" height="16" viewBox="0 0 16 16" fill="none">
      <path d="M8 2L13 4V8C13 11 8 14 8 14C8 14 3 11 3 8V4L8 2Z" stroke="currentColor" strokeWidth="1" fill="none" />
      <path d="M6 8L7.5 9.5L10 6.5" stroke="currentColor" strokeWidth="1" strokeLinecap="round" strokeLinejoin="round" />
    </svg>
  );
}
function CostIcon() {
  return (
    <svg width="16" height="16" viewBox="0 0 16 16" fill="none">
      <circle cx="8" cy="8" r="5.5" stroke="currentColor" strokeWidth="1" fill="none" />
      <path d="M8 5V11M6.5 6.5H9C9.5 6.5 10 7 10 7.5S9.5 8.5 9 8.5H7C6.5 8.5 6 9 6 9.5S6.5 10.5 7 10.5H9.5" stroke="currentColor" strokeWidth="0.75" strokeLinecap="round" />
    </svg>
  );
}
function LimitIcon() {
  return (
    <svg width="16" height="16" viewBox="0 0 16 16" fill="none">
      <rect x="2" y="3" width="12" height="10" stroke="currentColor" strokeWidth="1" fill="none" />
      <path d="M5 7L7 9L5 11" stroke="currentColor" strokeWidth="1" strokeLinecap="square" />
      <line x1="8" y1="11" x2="11" y2="11" stroke="currentColor" strokeWidth="1" strokeLinecap="square" />
    </svg>
  );
}
function PiiIcon() {
  return (
    <svg width="16" height="16" viewBox="0 0 16 16" fill="none">
      <circle cx="8" cy="6.5" r="3" stroke="currentColor" strokeWidth="1" fill="none" />
      <path d="M3 14C3 11.5 5 10 8 10C11 10 13 11.5 13 14" stroke="currentColor" strokeWidth="1" strokeLinecap="round" />
      <line x1="3" y1="3" x2="13" y2="13" stroke="var(--color-error)" strokeWidth="1.5" strokeLinecap="round" opacity="0.6" />
    </svg>
  );
}
function AuditIcon() {
  return (
    <svg width="16" height="16" viewBox="0 0 16 16" fill="none">
      <rect x="3" y="1.5" width="10" height="13" stroke="currentColor" strokeWidth="1" fill="none" />
      <line x1="5" y1="4.5" x2="11" y2="4.5" stroke="currentColor" strokeWidth="0.75" />
      <line x1="5" y1="7" x2="11" y2="7" stroke="currentColor" strokeWidth="0.75" />
      <line x1="5" y1="9.5" x2="9" y2="9.5" stroke="currentColor" strokeWidth="0.75" />
    </svg>
  );
}

const PIPELINE_STEPS: PipelineStep[] = [
  {
    id: "parse",
    label: "sql_parse",
    shortLabel: "PARSE",
    description: "AST validation via sqlglot",
    detail: "Blocks DDL/DML, prevents query stacking, validates syntax",
    icon: <ParseIcon />,
  },
  {
    id: "policy",
    label: "policy_check",
    shortLabel: "POLICY",
    description: "Schema & table enforcement",
    detail: "Blocked tables, schema annotations, read-only enforcement",
    icon: <PolicyIcon />,
  },
  {
    id: "cost",
    label: "cost_estimate",
    shortLabel: "COST",
    description: "EXPLAIN-based estimation",
    detail: "Pre-execution cost check, budget validation, expensive query warnings",
    icon: <CostIcon />,
  },
  {
    id: "limit",
    label: "row_limit",
    shortLabel: "LIMIT",
    description: "LIMIT injection/clamping",
    detail: "Prevents context overflow, enforces per-query row limits",
    icon: <LimitIcon />,
  },
  {
    id: "pii",
    label: "pii_redact",
    shortLabel: "PII",
    description: "Column-level redaction",
    detail: "Hash, mask, or drop flagged columns before returning results",
    icon: <PiiIcon />,
  },
  {
    id: "audit",
    label: "audit_log",
    shortLabel: "AUDIT",
    description: "Append-only compliance log",
    detail: "Full query chain JSONL, timestamps, execution metadata",
    icon: <AuditIcon />,
  },
];

function PipelineConnectorSVG({ active }: { active: boolean }) {
  return (
    <svg width="40" height="40" viewBox="0 0 40 40" fill="none" className="flex-shrink-0">
      {/* Dashed line with flow animation */}
      <line
        x1="0" y1="20" x2="40" y2="20"
        stroke={active ? "var(--color-success)" : "var(--color-border-hover)"}
        strokeWidth="1"
        strokeDasharray="3 3"
        className="pipeline-connector"
        opacity={active ? 0.6 : 0.3}
      />
      {/* Arrow head */}
      <path
        d="M32 16L38 20L32 24"
        stroke={active ? "var(--color-success)" : "var(--color-border-hover)"}
        strokeWidth="1"
        fill="none"
        strokeLinecap="round"
        strokeLinejoin="round"
        opacity={active ? 0.8 : 0.4}
      />
      {/* Flow dot */}
      <circle r="1.5" fill="var(--color-success)" opacity={active ? 0.8 : 0.3}>
        <animateMotion dur="1.2s" repeatCount="indefinite" path="M0,20 L40,20" />
      </circle>
    </svg>
  );
}

export function GovernancePipeline() {
  const [hoveredStep, setHoveredStep] = useState<string | null>(null);
  const [activeStage, setActiveStage] = useState(0);

  // Simulate data flowing through the pipeline
  useEffect(() => {
    const interval = setInterval(() => {
      setActiveStage((prev) => (prev + 1) % (PIPELINE_STEPS.length + 2));
    }, 2000);
    return () => clearInterval(interval);
  }, []);

  return (
    <div className="border border-[var(--color-border)] bg-[var(--color-bg-card)] overflow-hidden" style={{ overflow: "hidden" }}>
      {/* Header */}
      <div className="px-4 py-3 border-b border-[var(--color-border)] flex items-center justify-between">
        <div className="flex items-center gap-3">
          <svg width="16" height="16" viewBox="0 0 16 16" fill="none">
            <path d="M2 8h3l2-4 2 8 2-4h3" stroke="var(--color-success)" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round" />
          </svg>
          <span className="text-[12px] uppercase tracking-[0.15em] text-[var(--color-text-dim)]">
            governance pipeline
          </span>
        </div>
        <div className="flex items-center gap-3">
          <span className="flex items-center gap-1.5 text-[11px] text-[var(--color-success)] tracking-wider">
            <span className="relative flex h-1.5 w-1.5">
              <span className="animate-ping absolute inline-flex h-full w-full bg-[var(--color-success)] opacity-40" />
              <span className="relative inline-flex h-1.5 w-1.5 bg-[var(--color-success)]" />
            </span>
            active
          </span>
          <span className="text-[11px] text-[var(--color-text-dim)] tracking-wider px-2 py-0.5 border border-[var(--color-border)]">
            6 stages
          </span>
        </div>
      </div>

      {/* Pipeline visualization */}
      <div className="px-4 py-5 overflow-hidden">
        <div className="flex items-center justify-between overflow-hidden">
          {/* Input indicator */}
          <div className="flex items-center gap-1.5 flex-shrink-0 mr-1">
            <div className="transition-all duration-300">
              <svg width="20" height="20" viewBox="0 0 20 20" fill="none">
                <rect x="1" y="1" width="18" height="18" stroke={activeStage === 0 ? "var(--color-success)" : "var(--color-border-hover)"} strokeWidth="1" fill="none">
                  {activeStage === 0 && (
                    <animate attributeName="stroke-opacity" values="0.4;1;0.4" dur="1.5s" repeatCount="indefinite" />
                  )}
                </rect>
                <text x="10" y="13" textAnchor="middle" fill={activeStage === 0 ? "var(--color-success)" : "var(--color-text-dim)"} fontSize="8" fontFamily="monospace">SQL</text>
              </svg>
            </div>
            <svg width="16" height="16" viewBox="0 0 16 16" fill="none" className="flex-shrink-0">
              <path d="M3 8H13M10 5L13 8L10 11" stroke="var(--color-border-hover)" strokeWidth="1" strokeLinecap="round" strokeLinejoin="round" />
            </svg>
          </div>

          {PIPELINE_STEPS.map((step, i) => {
            const isActive = activeStage === i + 1;
            const isPassed = activeStage > i + 1;
            return (
              <div key={step.id} className="flex items-center flex-shrink-0">
                <div
                  className="relative group cursor-default transition-all duration-200"
                  onMouseEnter={() => setHoveredStep(step.id)}
                  onMouseLeave={() => setHoveredStep(null)}
                >
                  {/* Step card */}
                  <div className={`relative px-3 py-2.5 border transition-all duration-300 ${
                    isActive
                      ? "border-[var(--color-success)]/40 bg-[var(--color-success)]/5"
                      : hoveredStep === step.id
                        ? "border-[var(--color-border-active)] bg-[var(--color-bg-hover)]"
                        : "border-[var(--color-border)] bg-[var(--color-bg)]"
                  }`}>
                    {/* Active glow */}
                    {isActive && (
                      <div className="absolute inset-0 pointer-events-none overflow-hidden">
                        <div className="absolute inset-0 border border-[var(--color-success)]/20 animate-pulse" style={{ animationDuration: "2s" }} />
                      </div>
                    )}

                    {/* Step header with icon */}
                    <div className="flex items-center gap-2 mb-1.5">
                      <span className={`transition-colors duration-300 ${
                        isActive ? "text-[var(--color-success)]" : isPassed ? "text-[var(--color-success)]/60" : hoveredStep === step.id ? "text-[var(--color-text-muted)]" : "text-[var(--color-text-dim)]"
                      }`}>
                        {step.icon}
                      </span>
                      <span className={`text-[11px] tabular-nums tracking-wider transition-colors duration-300 ${
                        isActive ? "text-[var(--color-success)]" : hoveredStep === step.id ? "text-[var(--color-text-muted)]" : "text-[var(--color-text-dim)]"
                      }`}>
                        {String(i + 1).padStart(2, "0")}
                      </span>
                      {isPassed && (
                        <svg width="10" height="10" viewBox="0 0 10 10" fill="none" className="flex-shrink-0">
                          <path d="M2 5L4 7L8 3" stroke="var(--color-success)" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round" opacity="0.6" />
                        </svg>
                      )}
                    </div>

                    {/* Step label */}
                    <div className={`text-[12px] font-medium tracking-wide transition-colors duration-300 ${
                      isActive ? "text-[var(--color-text)] glow-text" : hoveredStep === step.id ? "text-[var(--color-text)]" : "text-[var(--color-text-muted)]"
                    }`}>
                      {step.label}
                    </div>

                    {/* Description */}
                    <div className="text-[11px] text-[var(--color-text-dim)] mt-1 tracking-wider max-w-[140px]">
                      {step.description}
                    </div>
                  </div>

                  {/* Hover tooltip with detail */}
                  {hoveredStep === step.id && (
                    <div className="absolute top-full left-0 right-0 mt-1 p-2.5 bg-[var(--color-bg-elevated)] border border-[var(--color-border)] z-10 animate-fade-in">
                      <p className="text-[11px] text-[var(--color-text-muted)] tracking-wider leading-relaxed">
                        {step.detail}
                      </p>
                    </div>
                  )}
                </div>

                {/* Connector */}
                {i < PIPELINE_STEPS.length - 1 && (
                  <PipelineConnectorSVG active={activeStage > i + 1} />
                )}
              </div>
            );
          })}

          {/* Output indicator */}
          <div className="flex items-center gap-1.5 flex-shrink-0 ml-1">
            <svg width="16" height="16" viewBox="0 0 16 16" fill="none" className="flex-shrink-0">
              <path d="M3 8H13M10 5L13 8L10 11" stroke="var(--color-border-hover)" strokeWidth="1" strokeLinecap="round" strokeLinejoin="round" />
            </svg>
            <div className="transition-all duration-300">
              <svg width="20" height="20" viewBox="0 0 20 20" fill="none">
                <rect x="1" y="1" width="18" height="18"
                  stroke={activeStage >= PIPELINE_STEPS.length + 1 ? "var(--color-success)" : "var(--color-border-hover)"}
                  strokeWidth="1"
                  fill={activeStage >= PIPELINE_STEPS.length + 1 ? "var(--color-success)" : "none"}
                  fillOpacity={activeStage >= PIPELINE_STEPS.length + 1 ? 0.15 : 0}
                />
                <path d="M6 10L8.5 12.5L14 7" stroke="var(--color-success)" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round"
                  opacity={activeStage >= PIPELINE_STEPS.length + 1 ? 1 : 0.3}
                />
              </svg>
            </div>
          </div>
        </div>

        {/* Footer note */}
        <div className="flex items-center gap-2 mt-4 pt-3 border-t border-[var(--color-border)]">
          <svg width="12" height="12" viewBox="0 0 12 12" fill="none">
            <path d="M6 1v10M1 6h10" stroke="var(--color-text-dim)" strokeWidth="1" strokeLinecap="round" />
          </svg>
          <span className="text-[11px] text-[var(--color-text-dim)] tracking-wider">
            every query passes through all 6 stages before results reach the agent
          </span>
          <span className="ml-auto text-[11px] text-[var(--color-text-dim)] tracking-wider tabular-nums">
            ~2ms overhead
          </span>
        </div>
      </div>
    </div>
  );
}
