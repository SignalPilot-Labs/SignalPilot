"use client";

import Link from "next/link";
import { ArrowLeft, ShieldCheck } from "lucide-react";
import { useAppAuth } from "~/lib/auth-context";
import { PageHeader } from "~/components/ui/page-header";

/**
 * The full-page notice a member sees on a direct link to an admin-only page.
 * Never a 403 toast: the page says who manages it and offers a way back.
 */
export function AdminOnlyPage({
  title,
  subtitle = "settings",
  what,
  backHref = "/dashboard",
  backLabel = "back to dashboard",
}: {
  title: string;
  subtitle?: string;
  /** What is managed here, in a few words: "billing and plans". */
  what?: string;
  backHref?: string;
  backLabel?: string;
}) {
  const { activeOrgName } = useAppAuth();
  const org = activeOrgName ?? "your organization";
  return (
    <div className="p-8 max-w-4xl animate-fade-in" data-testid="admin-only-page">
      <PageHeader title={title} subtitle={subtitle} description="org admins manage this" />
      <div className="border border-[var(--color-border)] bg-[var(--color-bg-card)] rounded-[14px] p-6 flex items-start gap-3">
        <ShieldCheck
          className="w-4 h-4 text-[var(--color-text-dim)] mt-0.5 flex-shrink-0"
          strokeWidth={1.5}
        />
        <div className="space-y-2">
          <p className="text-[13px] text-[var(--color-text)]">Org admins manage this</p>
          <p className="text-[12px] text-[var(--color-text-dim)] leading-relaxed">
            {what ? `${what[0].toUpperCase()}${what.slice(1)} for ` : "This page is configured for "}
            <span className="text-[var(--color-text-muted)]">{org}</span>
            {" by its org admins. Ask an admin if something here needs to change."}
          </p>
          <Link
            href={backHref}
            className="inline-flex items-center gap-1.5 mt-1 text-[12px] text-[var(--color-text-dim)] hover:text-[var(--color-text)] transition-colors"
          >
            <ArrowLeft className="w-3 h-3" />
            {backLabel}
          </Link>
        </div>
      </div>
    </div>
  );
}
