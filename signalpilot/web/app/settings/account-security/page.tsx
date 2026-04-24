"use client";

/**
 * Account Security settings page.
 * Cloud-mode only — local mode renders a "not available" stub.
 *
 * AccountSecurityClient is dynamically imported with ssr:false because
 * @clerk/nextjs hooks (useUser, useReverification) must not evaluate
 * during SSR or in local mode (no ClerkProvider present in local builds).
 * Next.js 16 requires ssr:false to be declared in a Client Component.
 */

import dynamic from "next/dynamic";
import { Info } from "lucide-react";
import { PageHeader } from "@/components/ui/page-header";
import { DashboardSkeleton } from "@/components/ui/skeleton";
import { useAppAuth } from "@/lib/auth-context";

const AccountSecurityClient = dynamic(
  () => import("./account-security-client"),
  {
    ssr: false,
    loading: () => <DashboardSkeleton />,
  },
);

export default function AccountSecurityPage() {
  const { isCloudMode, isLoaded } = useAppAuth();

  if (!isLoaded) {
    return <DashboardSkeleton />;
  }

  if (!isCloudMode) {
    return (
      <div className="p-8 max-w-3xl animate-fade-in">
        <PageHeader
          title="account security"
          subtitle="security"
          description="manage your password, multi-factor authentication, and backup codes"
        />
        <div className="border border-[var(--color-border)] bg-[var(--color-bg-card)]">
          <div className="p-6 flex items-start gap-3">
            <Info
              className="w-3.5 h-3.5 text-[var(--color-text-dim)] mt-0.5 flex-shrink-0"
              strokeWidth={1.5}
            />
            <p className="text-[12px] text-[var(--color-text-dim)] tracking-wider leading-relaxed">
              account security settings are available in cloud mode. local
              deployments manage authentication directly. set{" "}
              <code className="text-[var(--color-text-muted)]">
                NEXT_PUBLIC_DEPLOYMENT_MODE=cloud
              </code>{" "}
              and configure clerk to manage mfa and passwords.
            </p>
          </div>
        </div>
      </div>
    );
  }

  return <AccountSecurityClient />;
}
