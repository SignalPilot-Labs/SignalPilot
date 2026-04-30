"use client";

/**
 * Top-level orchestrator for the team settings page.
 * Fetches org + membership data, computes permissions, renders sections.
 */

import { useUser, useOrganization } from "@clerk/nextjs";
import { Info } from "lucide-react";
import { PageHeaderSkeleton, CardSkeleton } from "@/components/ui/skeleton";
import { PageHeader, TerminalBar } from "@/components/ui/page-header";
import { TeamOverviewSection } from "@/components/team/team-overview-section";
import { TeamMembersSection } from "@/components/team/team-members-section";
import { TeamInvitationsSection } from "@/components/team/team-invitations-section";
import { TeamDangerSection } from "@/components/team/team-danger-section";
import { TeamEnterpriseSection } from "@/components/team/team-enterprise-section";
import { TeamDomainsSection } from "@/components/team/team-domains-section";
import { useTeamPermissions } from "@/lib/team/use-team-permissions";

export default function TeamClient() {
  const { user, isLoaded: userLoaded } = useUser();
  const { organization, membership, isLoaded: orgLoaded } = useOrganization();

  const isLoaded = userLoaded && orgLoaded;
  const perms = useTeamPermissions();

  if (!isLoaded) {
    return (
      <div className="p-8 max-w-3xl" aria-busy="true">
        <PageHeaderSkeleton />
        <div className="space-y-px">
          {[1, 2, 3].map((i) => <CardSkeleton key={i} />)}
        </div>
      </div>
    );
  }

  if (!organization || !user) {
    return (
      <div className="p-8 max-w-3xl">
        <div className="border border-[var(--color-border)] bg-[var(--color-bg-card)]">
          <div className="p-6 flex items-start gap-3">
            <Info className="w-3.5 h-3.5 text-[var(--color-text-dim)] mt-0.5 flex-shrink-0" strokeWidth={1.5} />
            <p className="text-[12px] text-[var(--color-text-dim)] tracking-wider leading-relaxed">
              no active team. use the team switcher to create or select one.
            </p>
          </div>
        </div>
      </div>
    );
  }

  const idPreview = `${organization.id.slice(0, 12)}…`;
  const membersCount = organization.membersCount ?? 0;

  return (
    <div className="p-8 max-w-3xl animate-fade-in">
      <PageHeader
        title="team"
        subtitle="settings"
        description="manage your team members, invitations, and team settings"
      />

      <TerminalBar path={`team --id ${idPreview}`}>
        <span className="text-xs text-[var(--color-text-dim)] font-mono">
          {organization.name}{" "}
          <span className="text-[var(--color-text-muted)]">
            · {membersCount} member{membersCount !== 1 ? "s" : ""}
          </span>
        </span>
      </TerminalBar>

      <TeamOverviewSection org={organization} perms={perms} />
      <TeamMembersSection org={organization} me={membership} perms={perms} />
      <TeamInvitationsSection org={organization} perms={perms} />
      {/* <TeamEnterpriseSection perms={perms} /> — requires Clerk paid plan */}
      {/* <TeamDomainsSection perms={perms} org={organization} /> — requires Clerk paid plan */}
      {perms.canDelete && (
        <TeamDangerSection org={organization} perms={perms} user={user} />
      )}
    </div>
  );
}
