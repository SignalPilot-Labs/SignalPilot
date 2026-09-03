"use client";

import { Building2, Plus, User } from "lucide-react";
import type { Connector } from "~/lib/api/mcp-connectors";
import { Skeleton } from "~/components/ui/skeleton";
import { EmptyState, EmptySandbox } from "~/components/ui/empty-states";
import { ConnectorRow, type ConnectorRowProps } from "./connector-row";
import { Button } from "./ui";

type SectionProps = Omit<ConnectorRowProps, "connector"> & {
  connectors: Connector[];
  scope: "org" | "personal";
  onAdd: (scope: "org" | "personal") => void;
  personalAllowed: boolean;
};

function Section({ connectors, scope, isAdmin, onAdd, personalAllowed, ...row }: SectionProps) {
  const isOrg = scope === "org";
  const title = isOrg ? "Organization" : "Personal";
  const blurb = isOrg
    ? isAdmin
      ? "Available to everyone. Each member signs in with their own account where a provider asks for it."
      : "Provided by your organization. Turn any of them off for yourself."
    : "Only you can use these.";
  const canAdd = isOrg ? isAdmin : personalAllowed;
  return (
    <section aria-labelledby={`connectors-${scope}`} data-testid={`connectors-section-${scope}`}>
      <div className="mb-3 flex items-end justify-between gap-4">
        <div className="min-w-0">
          <div className="flex items-center gap-2">
            {isOrg ? (
              <Building2 className="h-3.5 w-3.5 text-[var(--color-text-dim)]" aria-hidden="true" />
            ) : (
              <User className="h-3.5 w-3.5 text-[var(--color-text-dim)]" aria-hidden="true" />
            )}
            <h2 id={`connectors-${scope}`} className="text-[13px] font-semibold text-[var(--color-text)]">
              {title}
            </h2>
            {connectors.length > 0 && (
              <span className="text-[11.5px] tabular-nums text-[var(--color-text-dim)]">
                {connectors.length}
              </span>
            )}
          </div>
          <p className="mt-0.5 text-[12px] text-[var(--color-text-dim)]">{blurb}</p>
        </div>
        {canAdd && connectors.length > 0 && (
          <Button
            variant="ghost"
            onClick={() => onAdd(scope)}
            data-testid={`connectors-add-${scope}`}
            className="min-h-[32px] px-2.5 text-[12px]"
          >
            <Plus className="h-3.5 w-3.5" aria-hidden="true" />
            Add
          </Button>
        )}
      </div>
      {connectors.length === 0 ? (
        <div className="rounded-[var(--radius-card)] border border-dashed border-[var(--color-border)] px-4 py-5 text-[12.5px] text-[var(--color-text-dim)]">
          {isOrg ? (
            isAdmin ? (
              <span className="flex flex-wrap items-center gap-x-3 gap-y-2">
                Nothing shared with the team yet.
                <button
                  type="button"
                  onClick={() => onAdd("org")}
                  data-testid="connectors-add-org-empty"
                  className="text-[var(--color-text)] underline decoration-[var(--color-border-hover)] underline-offset-4 hover:decoration-[var(--color-text)]"
                >
                  Add one for everyone
                </button>
              </span>
            ) : (
              "Your organization hasn't shared any connectors yet."
            )
          ) : personalAllowed ? (
            <span className="flex flex-wrap items-center gap-x-3 gap-y-2">
              Add a personal connector only you can use.
              <button
                type="button"
                onClick={() => onAdd("personal")}
                data-testid="connectors-add-personal-empty"
                className="text-[var(--color-text)] underline decoration-[var(--color-border-hover)] underline-offset-4 hover:decoration-[var(--color-text)]"
              >
                Add connector
              </button>
            </span>
          ) : (
            "Your organization doesn't allow personal connectors."
          )}
        </div>
      ) : (
        // No overflow-hidden: the row kebab renders in a body-level portal,
        // and the stagger entrance must never clip anything a row pops out.
        <div
          className="divide-y divide-[var(--color-border)] rounded-[var(--radius-card)] border border-[var(--color-border)] bg-[var(--color-bg-card)] stagger-fade-in [&>*:first-child]:rounded-t-[var(--radius-card)] [&>*:last-child]:rounded-b-[var(--radius-card)]"
          data-testid={`connectors-rows-${scope}`}
        >
          {connectors.map((connector) => (
            <ConnectorRow key={connector.id} connector={connector} isAdmin={isAdmin} {...row} />
          ))}
        </div>
      )}
    </section>
  );
}

export function ConnectorsListSkeleton() {
  return (
    <div className="space-y-8" aria-busy="true" data-testid="connectors-skeleton">
      {[3, 2].map((rows, section) => (
        <div key={section}>
          <div className="mb-3 space-y-1.5">
            <Skeleton className="h-3 w-28" />
            <Skeleton className="h-2 w-64" />
          </div>
          <div className="divide-y divide-[var(--color-border)] overflow-hidden rounded-[var(--radius-card)] border border-[var(--color-border)] bg-[var(--color-bg-card)]">
            {Array.from({ length: rows }, (_, i) => (
              <div key={i} className="flex min-h-[64px] items-center gap-4 px-4">
                <Skeleton className="h-9 w-9 rounded-[10px]" />
                <div className="flex-1 space-y-2">
                  <Skeleton className="h-3 w-32" />
                  <Skeleton className="h-2 w-48" />
                </div>
                <Skeleton className="h-5 w-24 rounded-full" />
                <Skeleton className="hidden h-2.5 w-20 md:block" />
                <Skeleton className="h-4 w-8 rounded-full" />
              </div>
            ))}
          </div>
        </div>
      ))}
    </div>
  );
}

/**
 * Both sections, or the single inviting empty state when there is nothing
 * to list at all.
 */
export function ConnectorsList({
  connectors,
  isAdmin,
  personalAllowed,
  onAdd,
  ...row
}: Omit<ConnectorRowProps, "connector"> & {
  connectors: Connector[];
  personalAllowed: boolean;
  onAdd: (scope: "org" | "personal") => void;
}) {
  const org = connectors.filter((c) => c.scope === "org");
  const personal = connectors.filter((c) => c.scope === "personal");
  if (connectors.length === 0) {
    return (
      <div data-testid="connectors-empty">
        <EmptyState
          icon={EmptySandbox}
          title="No connectors yet"
          description="Give the agent tools from another service. Paste a server URL or a command to start."
          action={
            <Button variant="primary" onClick={() => onAdd(isAdmin ? "org" : "personal")} data-testid="connectors-add-first">
              <Plus className="h-3.5 w-3.5" aria-hidden="true" />
              Add connector
            </Button>
          }
        />
      </div>
    );
  }
  return (
    <div className="space-y-9">
      <Section
        scope="org"
        connectors={org}
        isAdmin={isAdmin}
        personalAllowed={personalAllowed}
        onAdd={onAdd}
        {...row}
      />
      <Section
        scope="personal"
        connectors={personal}
        isAdmin={isAdmin}
        personalAllowed={personalAllowed}
        onAdd={onAdd}
        {...row}
      />
    </div>
  );
}
