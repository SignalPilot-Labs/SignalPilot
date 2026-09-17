"use client";

/**
 * /settings/usage/me: the signed-in user's own usage window with a
 * conversations table (linking into /chats/<id>) and a connections table.
 */

import { useEffect, useState } from "react";
import Link from "next/link";
import { Database, MessageSquare } from "lucide-react";
import { getMyUsage, type UsageDays } from "~/lib/api/usage";
import { useAppAuth } from "~/lib/auth-context";
import { useTeamPermissions } from "~/lib/team/use-team-permissions";
import type { ConnectionUsage, ConversationUsage, MyUsageResponse } from "~/lib/types";
import { formatCount, formatUsd, toEpochSeconds } from "~/lib/usage-format";
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

function ConversationRow({ c }: { c: ConversationUsage }) {
  const last = toEpochSeconds(c.last_activity_at);
  return (
    <TableRow testId="usage-conversation-row">
      <span className="flex-1 min-w-[160px]">
        <Link
          href={`/chats/${c.conversation_id}`}
          className="text-xs text-[var(--color-text-muted)] hover:text-[var(--color-text)] underline-offset-2 hover:underline truncate block transition-colors"
        >
          {c.title || "untitled conversation"}
        </Link>
      </span>
      <Cell>{formatCount(c.chat_runs)}</Cell>
      <Cell width="w-24">{formatUsd(c.cost_usd)}</Cell>
      <Cell width="w-28">{last ? <TimeAgo timestamp={last} className="text-[12px]" /> : "—"}</Cell>
    </TableRow>
  );
}

function ConversationsTable({ rows }: { rows: ConversationUsage[] }) {
  return (
    <TableShell>
      <TableHeaderRow>
        <HeaderCell grow>conversation</HeaderCell>
        <HeaderCell>runs</HeaderCell>
        <HeaderCell width="w-24">cost</HeaderCell>
        <HeaderCell width="w-28">last activity</HeaderCell>
      </TableHeaderRow>
      {rows.length === 0 ? (
        <EmptyRows>no conversations in this period</EmptyRows>
      ) : (
        rows.map((c) => <ConversationRow key={c.conversation_id} c={c} />)
      )}
    </TableShell>
  );
}

function ConnectionRow({ c }: { c: ConnectionUsage }) {
  return (
    <TableRow testId="usage-connection-row">
      <Cell grow mono={false}>
        <span className="text-xs text-[var(--color-text-muted)]">{c.connection_name}</span>
      </Cell>
      <Cell>{formatCount(c.queries)}</Cell>
      <Cell width="w-24">{formatCount(c.rows_returned)}</Cell>
      <Cell>{formatCount(c.blocked_queries)}</Cell>
    </TableRow>
  );
}

function ConnectionsTable({ rows }: { rows: ConnectionUsage[] }) {
  return (
    <TableShell>
      <TableHeaderRow>
        <HeaderCell grow>connection</HeaderCell>
        <HeaderCell>queries</HeaderCell>
        <HeaderCell width="w-24">rows</HeaderCell>
        <HeaderCell>blocked</HeaderCell>
      </TableHeaderRow>
      {rows.length === 0 ? (
        <EmptyRows>no queries in this period</EmptyRows>
      ) : (
        rows.map((c) => <ConnectionRow key={c.connection_name} c={c} />)
      )}
    </TableShell>
  );
}

function MyUsageContent({ days, onDays }: { days: UsageDays; onDays: (d: UsageDays) => void }) {
  const [data, setData] = useState<MyUsageResponse | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;
    setData(null);
    setError(null);
    getMyUsage(days)
      .then((res) => { if (!cancelled) setData(res); })
      .catch((e: unknown) => { if (!cancelled) setError(e instanceof Error ? e.message : String(e)); });
    return () => { cancelled = true; };
  }, [days]);

  if (error) return <Notice testId="usage-error">Unable to load your usage. {error}</Notice>;
  if (!data) return <UsageSkeleton />;

  return (
    <>
      <div className="flex items-center justify-between mb-5">
        <span className="text-[12px] text-[var(--color-text-dim)]">
          {formatCount(data.totals.conversations)} conversations, {formatCount(data.totals.chat_runs)} runs
        </span>
        <PeriodSelector value={days} onChange={onDays} />
      </div>
      <TotalsRow totals={data.totals} />
      <DailySection daily={data.daily} days={data.window.days} />
      <section className="mb-8">
        <SectionHeader icon={MessageSquare} title="conversations" />
        <ConversationsTable rows={data.conversations} />
      </section>
      <section>
        <SectionHeader icon={Database} title="connections" />
        <ConnectionsTable rows={data.connections} />
      </section>
    </>
  );
}

export function MyUsagePage() {
  const { isCloudMode, isLoaded } = useAppAuth();
  const { isAdmin } = useTeamPermissions();
  const [days, setDays] = useState<UsageDays>(30);

  if (!isLoaded) return <UsageSkeleton />;

  return (
    <div className="p-8 max-w-4xl animate-fade-in">
      <PageHeader
        title="usage"
        subtitle="my usage"
        description="your chat, token, and query usage"
        tabs={usageTabs(!isCloudMode || isAdmin)}
      />
      <MyUsageContent days={days} onDays={setDays} />
    </div>
  );
}
