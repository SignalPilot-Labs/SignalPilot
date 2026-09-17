"use client";

/**
 * /settings/usage/members: organization-wide usage per member. Rendered for
 * org admins only (the `usage.org` permission from usePermissions); everyone
 * else, and any 403 from the gateway, sees a short admins-only notice.
 */

import { useEffect, useMemo, useState } from "react";
import { useOrganization } from "@clerk/nextjs";
import { Users } from "lucide-react";
import { getOrgUsage, type UsageDays } from "~/lib/api/usage";
import { requestErrorStatus } from "~/lib/api/client";
import { useAppAuth } from "~/lib/auth-context";
import { usePermissions } from "~/lib/hooks/use-permissions";
import type { MemberUsage, OrgUsageResponse } from "~/lib/types";
import { formatCompact, formatCount, formatUsd, toEpochSeconds } from "~/lib/usage-format";
import { PageHeader } from "~/components/ui/page-header";
import { SectionHeader } from "~/components/ui/section-header";
import { TimeAgo } from "~/components/ui/time-ago";
import { UsageSkeleton } from "~/components/ui/skeleton";
import {
  Cell,
  DailySection,
  EmptyRows,
  HeaderCell,
  Notice,
  PeriodSelector,
  TableHeaderRow,
  TableRow,
  TableShell,
  TotalsRow,
  usageTabs,
} from "./usage-shared";

type SortKey = "cost_usd" | "chat_runs";

interface MemberIdentity {
  name: string;
  email: string | null;
}

/** Name and email per user id, from the Clerk org membership list. */
function useMemberIdentities(): Map<string, MemberIdentity> {
  const { memberships } = useOrganization({
    memberships: { pageSize: 100, keepPreviousData: true },
  });
  return useMemo(() => {
    const map = new Map<string, MemberIdentity>();
    for (const m of memberships?.data ?? []) {
      const p = m.publicUserData;
      if (!p?.userId) continue;
      const name = [p.firstName, p.lastName].filter(Boolean).join(" ") || p.identifier || p.userId;
      map.set(p.userId, { name, email: p.identifier ?? null });
    }
    return map;
  }, [memberships?.data]);
}

function MembersHeader({ sort, onSort }: { sort: SortKey; onSort: (k: SortKey) => void }) {
  return (
    <TableHeaderRow>
      <HeaderCell grow>member</HeaderCell>
      <HeaderCell sortable active={sort === "chat_runs"} onClick={() => onSort("chat_runs")}>runs</HeaderCell>
      <HeaderCell width="w-16">convs</HeaderCell>
      <HeaderCell width="w-28">tokens in / out</HeaderCell>
      <HeaderCell sortable active={sort === "cost_usd"} onClick={() => onSort("cost_usd")} width="w-24">cost</HeaderCell>
      <HeaderCell width="w-16">queries</HeaderCell>
      <HeaderCell width="w-16">blocked</HeaderCell>
      <HeaderCell width="w-24">last active</HeaderCell>
    </TableHeaderRow>
  );
}

function MemberRow({ m, identity }: { m: MemberUsage; identity?: MemberIdentity }) {
  const lastActive = toEpochSeconds(m.last_active_at);
  return (
    <TableRow testId="usage-member-row">
      <span className="flex-1 min-w-[160px]">
        <span className="block text-xs text-[var(--color-text-muted)] truncate">
          {identity?.name ?? m.user_id}
        </span>
        <span className="block text-[11px] text-[var(--color-text-dim)] font-mono truncate">
          {identity?.email ?? m.user_id}
        </span>
      </span>
      <Cell>{formatCount(m.chat_runs)}</Cell>
      <Cell width="w-16">{formatCount(m.conversations)}</Cell>
      <Cell width="w-28">{formatCompact(m.input_tokens)} / {formatCompact(m.output_tokens)}</Cell>
      <Cell width="w-24">{formatUsd(m.cost_usd)}</Cell>
      <Cell width="w-16">{formatCount(m.queries)}</Cell>
      <Cell width="w-16">{formatCount(m.blocked_queries)}</Cell>
      <Cell width="w-24">
        {lastActive ? <TimeAgo timestamp={lastActive} className="text-[12px]" /> : "—"}
      </Cell>
    </TableRow>
  );
}

function MembersContent({ days, onDays }: { days: UsageDays; onDays: (d: UsageDays) => void }) {
  const [data, setData] = useState<OrgUsageResponse | null>(null);
  const [error, setError] = useState<{ status: number | null; message: string } | null>(null);
  const [sort, setSort] = useState<SortKey>("cost_usd");
  const identities = useMemberIdentities();

  useEffect(() => {
    let cancelled = false;
    setData(null);
    setError(null);
    getOrgUsage(days)
      .then((res) => { if (!cancelled) setData(res); })
      .catch((e: unknown) => {
        if (cancelled) return;
        setError({ status: requestErrorStatus(e), message: e instanceof Error ? e.message : String(e) });
      });
    return () => { cancelled = true; };
  }, [days]);

  const members = useMemo(
    () => (data ? [...data.members].sort((a, b) => b[sort] - a[sort]) : []),
    [data, sort],
  );

  if (error?.status === 403) return <Notice testId="usage-admins-only">Admins only. Organization usage is visible to org admins.</Notice>;
  if (error) return <Notice testId="usage-error">Unable to load organization usage. {error.message}</Notice>;
  if (!data) return <UsageSkeleton />;

  return (
    <>
      <div className="flex items-center justify-between mb-5">
        <span className="text-[12px] text-[var(--color-text-dim)]">
          {formatCount(data.members.length)} members with activity
        </span>
        <PeriodSelector value={days} onChange={onDays} />
      </div>
      <TotalsRow totals={data.totals} />
      <DailySection daily={data.daily} days={data.window.days} />
      <section>
        <SectionHeader icon={Users} title="members" />
        <TableShell>
          <MembersHeader sort={sort} onSort={setSort} />
          {members.length === 0 ? (
            <EmptyRows>no member activity in this period</EmptyRows>
          ) : (
            members.map((m) => <MemberRow key={m.user_id} m={m} identity={identities.get(m.user_id)} />)
          )}
        </TableShell>
      </section>
    </>
  );
}

export function MembersUsagePage() {
  const { isCloudMode, isLoaded } = useAppAuth();
  const { can, loaded: permissionsLoaded } = usePermissions();
  const [days, setDays] = useState<UsageDays>(30);
  // Local mode has no organization roles; the gateway decides there.
  const allowed = !isCloudMode || can("usage.org");

  // Wait for the role so a member never requests the org totals first.
  if (!isLoaded || (isCloudMode && !permissionsLoaded)) return <UsageSkeleton />;

  return (
    <div className="p-8 max-w-4xl animate-fade-in">
      <PageHeader
        title="usage"
        subtitle="members"
        description="chat, token, and query usage per organization member"
        tabs={usageTabs(allowed)}
      />
      {allowed ? (
        <MembersContent days={days} onDays={setDays} />
      ) : (
        <Notice testId="usage-admins-only">Admins only. Organization usage is visible to org admins.</Notice>
      )}
    </div>
  );
}
