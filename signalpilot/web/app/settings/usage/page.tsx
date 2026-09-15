"use client";

import { AlertTriangle } from "lucide-react";
import { useAppAuth } from "~/lib/auth-context";
import { usePermissions } from "~/lib/hooks/use-permissions";
import { UsageSkeleton } from "~/components/ui/skeleton";
import {
  MyUsageContent,
  OrgUsageContent,
  USAGE_HEADER,
} from "~/components/billing/usage-page-content";

// ---------------------------------------------------------------------------
// Gate — usage lives on the billing backend, so it is a cloud-mode page.
// Admins get the org view; members get their own rows ("my usage").
// ---------------------------------------------------------------------------

export default function UsagePage() {
  const { isCloudMode, isLoaded } = useAppAuth();
  const { can, loaded: permissionsLoaded } = usePermissions();

  if (!isLoaded) {
    return <UsageSkeleton />;
  }

  if (!isCloudMode) {
    return (
      <div className="p-8 max-w-4xl animate-fade-in">
        {USAGE_HEADER}
        <div className="border border-[var(--color-border)] bg-[var(--color-bg-card)] rounded-[14px] p-6 flex items-start gap-3">
          <AlertTriangle
            className="w-3.5 h-3.5 text-[var(--color-text-dim)] mt-0.5 flex-shrink-0"
            strokeWidth={1.5}
          />
          <p className="text-[12px] text-[var(--color-text-dim)] leading-relaxed">
            credit usage is metered in cloud mode. local deployments are unlimited and nothing is
            metered. set{" "}
            <code className="text-[var(--color-text-muted)]">NEXT_PUBLIC_DEPLOYMENT_MODE=cloud</code>{" "}
            and configure clerk to enable this page.
          </p>
        </div>
      </div>
    );
  }

  // Wait for the role: an admin must not see "my usage" flash first, and a
  // member must never request the org totals (a 403 would read as an outage).
  if (!permissionsLoaded) {
    return <UsageSkeleton />;
  }

  return can("usage.org") ? <OrgUsageContent /> : <MyUsageContent />;
}
