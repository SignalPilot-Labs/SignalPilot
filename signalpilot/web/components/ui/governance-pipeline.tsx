"use client";

import { useState } from "react";

interface PipelineStep {
  id: string;
  label: string;
  shortLabel: string;
  description: string;
  detail: string;
}

const PIPELINE_STEPS: PipelineStep[] = [
  {
    id: "parse",
    label: "sql_parse",
    shortLabel: "PARSE",
    description: "AST validation via sqlglot",
    detail: "Blocks DDL/DML, prevents query stacking, validates syntax",
  },
  {
    id: "policy",
    label: "policy_check",
    shortLabel: "POLICY",
    description: "Schema & table enforcement",
    detail: "Blocked tables, schema annotations, read-only enforcement",
  },
  {
    id: "cost",
    label: "cost_estimate",
    shortLabel: "COST",
    description: "EXPLAIN-based estimation",
    detail: "Pre-execution cost check, budget validation, expensive query warnings",
  },
  {
    id: "limit",
    label: "row_limit",
    shortLabel: "LIMIT",
    description: "LIMIT injection/clamping",
    detail: "Prevents context overflow, enforces per-query row limits",
  },
  {
    id: "pii",
    label: "pii_redact",
    shortLabel: "PII",
    description: "Column-level redaction",
    detail: "Hash, mask, or drop flagged columns before returning results",
  },
  {
    id: "audit",
    label: "audit_log",
    shortLabel: "AUDIT",
    description: "Append-only compliance log",
    detail: "Full query chain JSONL, timestamps, execution metadata",
  },
];

function PipelineConnectorSVG() {
  return (
    <svg width="32" height="40" viewBox="0 0 32 40" fill="none" className="flex-shrink-0">
      {/* Dashed line with flow animation */}
      <line
        x1="0" y1="20" x2="32" y2="20"
        stroke="var(--color-border-hover)"
        strokeWidth="1"
        strokeDasharray="3 3"
        className="pipeline-connector"
      />
      {/* Arrow head */}
      <path
        d="M26 16L32 20L26 24"
        stroke="var(--color-border-hover)"
        strokeWidth="1"
        fill="none"
        strokeLinecap="round"
        strokeLinejoin="round"
      />
      {/* Flow dot */}
      <circle r="1.5" fill="var(--color-success)" opacity="0.6">
        <animateMotion dur="1.5s" repeatCount="indefinite" path="M0,20 L32,20" />
      </circle>
    </svg>
  );
}

export function GovernancePipeline() {
  const [hoveredStep, setHoveredStep] = useState<string | null>(null);

  return (
    <div className="border border-[var(--color-border)] bg-[var(--color-bg-card)] overflow-hidden">
      {/* Header */}
      <div className="px-4 py-3 border-b border-[var(--color-border)] flex items-center justify-between">
        <div className="flex items-center gap-3">
          <svg width="16" height="16" viewBox="0 0 16 16" fill="none">
            <path d="M2 8h3l2-4 2 8 2-4h3" stroke="var(--color-success)" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round" />
          </svg>
          <span className="text-[10px] uppercase tracking-[0.15em] text-[var(--color-text-dim)]">
            governance pipeline
          </span>
        </div>
        <span className="text-[9px] text-[var(--color-text-dim)] tracking-wider px-2 py-0.5 border border-[var(--color-border)]">
          6 stages
        </span>
      </div>

      {/* Pipeline visualization */}
      <div className="px-4 py-5">
        <div className="flex items-center justify-between overflow-x-auto">
          {/* Input indicator */}
          <div className="flex items-center gap-1 flex-shrink-0 mr-2">
            <svg width="14" height="14" viewBox="0 0 14 14" fill="none">
              <rect x="1" y="1" width="12" height="12" stroke="var(--color-success)" strokeWidth="1" fill="none" opacity="0.4" />
              <text x="7" y="10" textAnchor="middle" fill="var(--color-success)" fontSize="7" fontFamily="monospace">Q</text>
            </svg>
            <svg width="12" height="12" viewBox="0 0 12 12" fill="none" className="flex-shrink-0">
              <path d="M2 6H10M7 3L10 6L7 9" stroke="var(--color-border-hover)" strokeWidth="1" strokeLinecap="round" strokeLinejoin="round" />
            </svg>
          </div>
          {PIPELINE_STEPS.map((step, i) => (
            <div key={step.id} className="flex items-center flex-shrink-0">
              <div
                className={`relative group cursor-default transition-all ${
                  hoveredStep === step.id ? "transform -translate-y-0.5" : ""
                }`}
                onMouseEnter={() => setHoveredStep(step.id)}
                onMouseLeave={() => setHoveredStep(null)}
              >
                {/* Step card */}
                <div className={`relative px-3 py-2.5 border transition-all ${
                  hoveredStep === step.id
                    ? "border-[var(--color-border-active)] bg-[var(--color-bg-hover)]"
                    : "border-[var(--color-border)] bg-[var(--color-bg)]"
                }`}>
                  {/* Step number */}
                  <div className="flex items-center gap-2 mb-1.5">
                    <span className={`text-[9px] tabular-nums tracking-wider ${
                      hoveredStep === step.id ? "text-[var(--color-success)]" : "text-[var(--color-text-dim)]"
                    } transition-colors`}>
                      {String(i + 1).padStart(2, "0")}
                    </span>
                    <span className="text-[9px] text-[var(--color-text-dim)] tracking-wider">
                      {step.shortLabel}
                    </span>
                  </div>

                  {/* Step label */}
                  <div className={`text-[10px] font-medium tracking-wide transition-colors ${
                    hoveredStep === step.id ? "text-[var(--color-text)]" : "text-[var(--color-text-muted)]"
                  }`}>
                    {step.label}
                  </div>

                  {/* Description */}
                  <div className="text-[9px] text-[var(--color-text-dim)] mt-1 tracking-wider max-w-[140px]">
                    {step.description}
                  </div>
                </div>

                {/* Hover tooltip with detail */}
                {hoveredStep === step.id && (
                  <div className="absolute top-full left-0 right-0 mt-1 p-2 bg-[var(--color-bg-elevated)] border border-[var(--color-border)] z-10 animate-fade-in">
                    <p className="text-[9px] text-[var(--color-text-muted)] tracking-wider leading-relaxed">
                      {step.detail}
                    </p>
                  </div>
                )}
              </div>

              {/* Connector */}
              {i < PIPELINE_STEPS.length - 1 && <PipelineConnectorSVG />}
            </div>
          ))}
          {/* Output indicator */}
          <div className="flex items-center gap-1 flex-shrink-0 ml-2">
            <svg width="12" height="12" viewBox="0 0 12 12" fill="none" className="flex-shrink-0">
              <path d="M2 6H10M7 3L10 6L7 9" stroke="var(--color-border-hover)" strokeWidth="1" strokeLinecap="round" strokeLinejoin="round" />
            </svg>
            <svg width="14" height="14" viewBox="0 0 14 14" fill="none">
              <rect x="1" y="1" width="12" height="12" stroke="var(--color-success)" strokeWidth="1" fill="var(--color-success)" opacity="0.15" />
              <path d="M4 7L6 9L10 5" stroke="var(--color-success)" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round" />
            </svg>
          </div>
        </div>

        {/* Footer note */}
        <div className="flex items-center gap-2 mt-4 pt-3 border-t border-[var(--color-border)]">
          <svg width="12" height="12" viewBox="0 0 12 12" fill="none">
            <path d="M6 1v10M1 6h10" stroke="var(--color-text-dim)" strokeWidth="1" strokeLinecap="round" />
          </svg>
          <span className="text-[9px] text-[var(--color-text-dim)] tracking-wider">
            every query passes through all 6 stages before results reach the agent
          </span>
        </div>
      </div>
    </div>
  );
}
