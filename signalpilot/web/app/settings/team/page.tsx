"use client";

/**
 * Team settings page — cloud-mode only.
 * Dynamic import with ssr:false to keep Clerk hooks off the server.
 * Next.js 16 Turbopack requires "use client" on the file that calls dynamic().
 */

import dynamic from "next/dynamic";
import { Info, Loader2 } from "lucide-react";
import { PageHeader } from "@/components/ui/page-header";
import { useAppAuth } from "@/lib/auth-context";

const TeamClient = dynamic(
  () => import("./team-client"),
  {
    ssr: false,
    loading: () => (
      <div className="flex items-center justify-center h-96">
        <Loader2 className="w-5 h-5 animate-spin text-[var(--color-text-dim)]" />
      </div>
    ),
  },
);

export default function TeamPage() {
  const { isCloudMode, isLoaded } = useAppAuth();

  if (!isLoaded) {
    return (
      <div className="flex items-center justify-center h-96">
        <Loader2 className="w-5 h-5 animate-spin text-[var(--color-text-dim)]" />
      </div>
    );
  }

  if (!isCloudMode) {
    return (
      <div className="p-8 max-w-3xl animate-fade-in">
        <PageHeader
          title="team"
          subtitle="settings"
          description="manage your team members, invitations, and team settings"
        />
        <div className="border border-[var(--color-border)] bg-[var(--color-bg-card)]">
          <div className="p-6 flex items-start gap-3">
            <Info
              className="w-3.5 h-3.5 text-[var(--color-text-dim)] mt-0.5 flex-shrink-0"
              strokeWidth={1.5}
            />
            <p className="text-[12px] text-[var(--color-text-dim)] tracking-wider leading-relaxed">
              team settings are available in cloud mode. set{" "}
              <code className="text-[var(--color-text-muted)]">
                NEXT_PUBLIC_DEPLOYMENT_MODE=cloud
              </code>{" "}
              and configure clerk to manage teams.
            </p>
          </div>
        </div>
      </div>
    );
  }

  return <TeamClient />;
}
