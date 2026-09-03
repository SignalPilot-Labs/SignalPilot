"use client";

import { Plus } from "lucide-react";
import { useSearchParams } from "next/navigation";
import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import useSWR from "swr";
import type { Connector, ConnectorScope } from "~/lib/api/mcp-connectors";
import { getStandaloneChatBootstrap } from "~/lib/api/standalone-chat";
import { FIXTURE_ME } from "~/lib/mcp-connectors-fixture";
import { createFixtureConnectorsApi } from "~/lib/mcp-connectors-fixture-client";
import { ConfirmDialog } from "~/components/ui/confirm-dialog";
import { PageHeader } from "~/components/ui/page-header";
import { useToast } from "~/components/ui/toast";
import { AddConnectorModal } from "./add-connector-modal";
import { liveConnectorsApi } from "./connectors-api";
import { ConnectorsProvider, useConnectors } from "./connectors-context";
import { ConnectorDrawer, type DrawerTab } from "./connector-drawer";
import { ConnectorsList, ConnectorsListSkeleton } from "./connectors-list";
import { OrgPolicyCard } from "./org-policy-card";
import { Button, Notice } from "./ui";
import { useConnectorActions } from "./use-connector-actions";

/** Drop the one-shot params (sign-in callback, deep link) without a navigation. */
function stripParams(names: string[]) {
  if (typeof window === "undefined") return;
  const url = new URL(window.location.href);
  let changed = false;
  for (const name of names) {
    if (url.searchParams.has(name)) {
      url.searchParams.delete(name);
      changed = true;
    }
  }
  if (changed) window.history.replaceState(window.history.state, "", url.toString());
}

/** "3 members are signed in." for the org remove dialog; empty when unknown. */
export function describeSignedInMembers(count: number | null | undefined): string {
  if (typeof count !== "number") return "";
  if (count === 0) return "No one is signed in.";
  return count === 1 ? "1 member is signed in." : `${count} members are signed in.`;
}

function ConnectorsPageBody({ fixture }: { fixture: boolean }) {
  const { connectors, policy, isAdmin, loading, error, reload } = useConnectors();
  const actions = useConnectorActions();
  const { toast } = useToast();
  const params = useSearchParams();
  const [drawer, setDrawer] = useState<{ id: string; tab: DrawerTab } | null>(null);
  const [adding, setAdding] = useState<ConnectorScope | null>(null);
  const [removing, setRemoving] = useState<Connector | null>(null);
  const handledParams = useRef(false);

  const open = useCallback((connector: Connector, tab: DrawerTab = "tools") => {
    setDrawer({ id: connector.id, tab });
  }, []);
  const drawerConnector = drawer ? connectors.find((c) => c.id === drawer.id) ?? null : null;
  const personalAllowed = policy?.allow_personal ?? true;

  // One-shot URL params: the sign-in callback (`?connector=<id>&signin=ok|error`)
  // lands on the Access tab with a toast; `?open=<id>` (from the chat panel)
  // opens the drawer on Tools. Both are stripped so a reload doesn't replay them.
  const callbackId = params.get("connector");
  const signin = params.get("signin");
  const openId = params.get("open");
  useEffect(() => {
    if (loading || handledParams.current) return;
    if (!callbackId && !openId) return;
    handledParams.current = true;
    const target = connectors.find((c) => c.id === (callbackId ?? openId));
    if (callbackId) {
      if (target) {
        setDrawer({ id: target.id, tab: "access" });
        if (signin === "ok") toast(`Signed in to ${target.name} · applies to new chats`, "success");
        else if (signin === "error") toast(`The provider refused sign-in to ${target.name}. Try again from Access.`, "error", 6000);
      } else {
        toast("That connector is no longer here.", "info");
      }
    } else if (openId) {
      if (target) setDrawer({ id: target.id, tab: "tools" });
      else toast("That connector is no longer here.", "info");
    }
    stripParams(["connector", "signin", "open"]);
  }, [loading, connectors, callbackId, signin, openId, toast]);

  return (
    <div className="mx-auto max-w-[960px] p-5 sm:p-8">
      <PageHeader
        title="Connectors"
        subtitle={fixture ? "fixture" : "chat"}
        description="Give the agent tools from other services. Changes apply to new chats. Warehouse connections live under Connections."
        actions={
          !loading && connectors.length > 0 ? (
            <Button
              variant="primary"
              onClick={() => setAdding("personal")}
              disabled={!isAdmin && !personalAllowed}
              data-testid="connectors-add"
            >
              <Plus className="h-3.5 w-3.5" aria-hidden="true" />
              Add connector
            </Button>
          ) : null
        }
      />

      {error ? (
        <Notice tone="error" testId="connectors-error">
          <p className="font-medium">We couldn&apos;t load your connectors.</p>
          <p className="mt-0.5 text-[var(--color-text-muted)]">{error}</p>
          <div className="mt-2">
            <Button onClick={() => void reload()} className="min-h-[30px] px-2.5 text-[11.5px]">
              Try again
            </Button>
          </div>
        </Notice>
      ) : loading ? (
        <ConnectorsListSkeleton />
      ) : (
        <div className="space-y-9">
          <ConnectorsList
            connectors={connectors}
            isAdmin={isAdmin}
            personalAllowed={personalAllowed}
            actions={actions}
            onOpen={open}
            onRemove={setRemoving}
            onAdd={setAdding}
          />
          {isAdmin && policy && <OrgPolicyCard policy={policy} />}
        </div>
      )}

      {drawerConnector && drawer && (
        <ConnectorDrawer
          connector={drawerConnector}
          initialTab={drawer.tab}
          isAdmin={isAdmin}
          actions={actions}
          onClose={() => setDrawer(null)}
          onRemove={setRemoving}
        />
      )}

      <AddConnectorModal
        open={adding !== null}
        initialScope={adding ?? "personal"}
        onClose={() => setAdding(null)}
        onCreated={() => undefined}
        onOpenAccess={(connector) => {
          setAdding(null);
          open(connector, "access");
        }}
      />

      <ConfirmDialog
        open={removing !== null}
        titleCase="sentence"
        title={removing?.scope === "org" ? `Remove ${removing.name} for everyone?` : `Remove ${removing?.name ?? ""}?`}
        message={
          removing?.scope === "org"
            ? `${describeSignedInMembers(removing.signed_in_count)} The agent will no longer have its tools. Chats using it right now lose access immediately; they won't be stopped. All members' sign-ins and keys will be deleted.`.trim()
            : `The agent will no longer have its tools. Your saved keys will be deleted.${removing?.auth === "oauth" ? " You'll be signed out of it." : ""}`
        }
        confirmLabel="Remove connector"
        cancelLabel="Cancel"
        onCancel={() => setRemoving(null)}
        onConfirm={() => {
          const target = removing;
          setRemoving(null);
          if (!target) return;
          void actions.remove(target).then((ok) => {
            if (ok && drawer?.id === target.id) setDrawer(null);
          });
        }}
      />
    </div>
  );
}

/**
 * /settings/connectors. `?fixture=1` swaps in the in-memory API so the whole
 * surface runs without a gateway; `&admin=0` shows the member view and
 * `&empty=1` the empty state. Live mode is gated on the chat feature flag.
 */
export function ConnectorsPage() {
  const params = useSearchParams();
  const fixture = params.get("fixture") === "1";
  const fixtureAdmin = params.get("admin") !== "0";
  const fixtureEmpty = params.get("empty") === "1";
  const api = useMemo(
    () =>
      fixture
        ? createFixtureConnectorsApi({ isAdmin: fixtureAdmin, empty: fixtureEmpty })
        : liveConnectorsApi,
    [fixture, fixtureAdmin, fixtureEmpty],
  );
  const { data: bootstrap, isLoading } = useSWR(
    fixture ? null : "standalone-chat-bootstrap",
    getStandaloneChatBootstrap,
    { revalidateOnFocus: false },
  );
  const enabled = fixture || bootstrap?.enterprise_features.mcp_connectors === true;

  if (!fixture && isLoading) {
    return (
      <div className="mx-auto max-w-[960px] p-5 sm:p-8">
        <ConnectorsListSkeleton />
      </div>
    );
  }
  if (!enabled) {
    return (
      <div className="mx-auto max-w-[960px] p-5 sm:p-8">
        <PageHeader title="Connectors" subtitle="chat" description="Give the agent tools from other services." />
        <Notice tone="info" testId="connectors-disabled">
          Connectors aren&apos;t turned on for this workspace yet. Ask an administrator to enable them.
        </Notice>
      </div>
    );
  }
  return (
    <ConnectorsProvider api={api} fixture={fixture} currentUserId={fixture ? FIXTURE_ME : null}>
      <ConnectorsPageBody fixture={fixture} />
    </ConnectorsProvider>
  );
}
