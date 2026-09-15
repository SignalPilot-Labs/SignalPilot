"use client";

import { ServerOff } from "lucide-react";
import type { DeploymentCapabilities } from "~/lib/entitlement";

const CAPABILITY_HELP: Record<keyof DeploymentCapabilities, string> = {
  evals:
    "This deployment has no eval runner configured. Set SP_EVAL_RUNNER_IMAGE and the eval backend settings on the gateway to run evals here.",
  sandbox:
    "This deployment has no sandbox runtime configured. Set SP_SANDBOX_RUNTIME_PROVIDER on the gateway to run agent sandboxes here.",
};

/**
 * Operational notice: the org may use the feature, but this deployment is not
 * wired to run it. Never hides the feature; explains what is missing.
 */
export function NotAvailableInDeployment({
  capability,
  feature,
  compact = false,
}: {
  capability: keyof DeploymentCapabilities;
  feature: string;
  compact?: boolean;
}) {
  const card = (
    <div
      data-testid="not-available-in-deployment"
      className="border border-[var(--color-border)] bg-[var(--color-bg-card)] rounded-[14px] p-6 space-y-3"
    >
      <div className="flex items-center gap-2">
        <ServerOff className="w-3.5 h-3.5 text-[var(--color-text-dim)]" strokeWidth={1.5} />
        <span className="text-[11px] uppercase tracking-[0.08em] text-[var(--color-text-muted)]">
          not available in this deployment
        </span>
      </div>
      <p className="text-sm text-[var(--color-text)]">
        Your plan includes {feature}, but this deployment cannot run it.
      </p>
      <p className="text-xs text-[var(--color-text-dim)] leading-relaxed">
        {CAPABILITY_HELP[capability]}
      </p>
    </div>
  );

  if (compact) return card;

  return (
    <div className="p-8 animate-fade-in">
      <div className="max-w-md mx-auto mt-24">{card}</div>
    </div>
  );
}
