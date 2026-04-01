"use client";

interface PipelineStep {
  id: string;
  label: string;
  description: string;
}

const PIPELINE_STEPS: PipelineStep[] = [
  { id: "parse", label: "sql_parse", description: "AST validation via sqlglot — blocks DDL/DML, stacking" },
  { id: "policy", label: "policy_check", description: "Blocked tables, schema annotations, read-only enforcement" },
  { id: "cost", label: "cost_estimate", description: "EXPLAIN-based pre-estimation, budget check" },
  { id: "limit", label: "row_limit", description: "LIMIT injection/clamping to prevent context overflow" },
  { id: "pii", label: "pii_redact", description: "Hash/mask/drop flagged columns before returning results" },
  { id: "audit", label: "audit_log", description: "Append-only JSONL with full query chain for compliance" },
];

export function GovernancePipeline() {
  return (
    <div className="border border-[var(--color-border)] bg-[var(--color-bg-card)]">
      <div className="px-4 py-3 border-b border-[var(--color-border)] flex items-center gap-3">
        <span className="text-[10px] uppercase tracking-widest text-[var(--color-text-dim)]">
          governance pipeline
        </span>
        <span className="text-[9px] text-[var(--color-text-dim)]">
          6-stage query validation
        </span>
      </div>
      <div className="px-4 py-4">
        <div className="flex items-center gap-0 overflow-x-auto">
          {PIPELINE_STEPS.map((step, i) => (
            <div key={step.id} className="flex items-center flex-shrink-0">
              <div
                className="group relative px-3 py-2 border border-[var(--color-border)] bg-[var(--color-bg)] hover:bg-[var(--color-bg-hover)] hover:border-[var(--color-border-hover)] transition-all cursor-default"
                title={step.description}
              >
                <div className="text-[10px] font-medium text-[var(--color-text-muted)] group-hover:text-[var(--color-text)] transition-colors tracking-wide">
                  {step.label}
                </div>
                <div className="text-[9px] text-[var(--color-text-dim)] mt-0.5 tracking-wider">
                  step_{i + 1}
                </div>
              </div>
              {i < PIPELINE_STEPS.length - 1 && (
                <div className="w-4 h-px bg-[var(--color-border)] flex-shrink-0" />
              )}
            </div>
          ))}
        </div>
        <p className="text-[9px] text-[var(--color-text-dim)] mt-3 tracking-wider">
          every query passes through this pipeline before results reach the agent
        </p>
      </div>
    </div>
  );
}
