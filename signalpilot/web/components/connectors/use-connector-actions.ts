"use client";

// Member-level actions shared by the settings rows, the drawer, and the
// chat settings panel: optimistic, with a toast that says what happened.

import { useCallback, useState } from "react";
import type { Connector } from "~/lib/api/mcp-connectors";
import { useToast } from "~/components/ui/toast";
import { useConnectors } from "./connectors-context";

export function useConnectorActions() {
  const { api, upsert, removeLocal } = useConnectors();
  const { toast } = useToast();
  const [busyIds, setBusyIds] = useState<Set<string>>(() => new Set());

  const mark = useCallback((id: string, busy: boolean) => {
    setBusyIds((current) => {
      const next = new Set(current);
      if (busy) next.add(id);
      else next.delete(id);
      return next;
    });
  }, []);

  /** "On for me": the member's own switch. Applies to new chats. */
  const toggleForMe = useCallback(
    async (connector: Connector, enabled: boolean) => {
      const previous = connector.my_state;
      upsert({
        ...connector,
        my_state: {
          enabled,
          disabled_tools: previous?.disabled_tools ?? [],
          signed_in: previous?.signed_in ?? false,
          has_key: previous?.has_key ?? false,
          signed_in_at: previous?.signed_in_at ?? null,
        },
      });
      mark(connector.id, true);
      try {
        const state = await api.updateMe(connector.id, {
          enabled,
          disabled_tools: previous?.disabled_tools,
        });
        upsert({ ...connector, my_state: state });
        toast(
          enabled
            ? `${connector.name} is on for your new chats`
            : `${connector.name} is off for you · applies to new chats`,
          "success",
        );
      } catch (error) {
        upsert({ ...connector, my_state: previous });
        toast(`Couldn't update ${connector.name}: ${(error as Error).message}`, "error");
      } finally {
        mark(connector.id, false);
      }
    },
    [api, mark, toast, upsert],
  );

  /** Org-level enable switch (admin) or personal enable. */
  const setEnabled = useCallback(
    async (connector: Connector, enabled: boolean) => {
      mark(connector.id, true);
      try {
        const updated = await api.patch(connector.id, { enabled });
        upsert(updated);
        toast(
          enabled
            ? `${connector.name} turned on · applies to new chats`
            : connector.scope === "org"
              ? `${connector.name} turned off for everyone`
              : `${connector.name} turned off`,
          "success",
        );
      } catch (error) {
        toast(`Couldn't update ${connector.name}: ${(error as Error).message}`, "error");
      } finally {
        mark(connector.id, false);
      }
    },
    [api, mark, toast, upsert],
  );

  const signIn = useCallback(
    async (connector: Connector) => {
      mark(connector.id, true);
      try {
        const result = await api.signIn(connector.id);
        if (result.outcome === "signed_in") {
          upsert({
            ...connector,
            status: connector.status === "needs_sign_in" ? "connected" : connector.status,
            my_state: result.state,
          });
          toast(`Signed in to ${connector.name}`, "success");
        } else if (result.outcome === "cancelled") {
          toast("Sign-in was cancelled", "info");
        } else if (result.outcome === "blocked") {
          window.open(result.url, "_blank", "noopener");
          toast("Your browser blocked the sign-in window. It was opened in a new tab.", "info", 6000);
        } else {
          toast(`The provider refused sign-in: ${result.message}`, "error", 6000);
        }
        return result;
      } finally {
        mark(connector.id, false);
      }
    },
    [api, mark, toast, upsert],
  );

  const signOut = useCallback(
    async (connector: Connector, everyone = false) => {
      mark(connector.id, true);
      try {
        const state = await api.signOut(connector.id, everyone);
        upsert({
          ...connector,
          status: connector.scope === "personal" && connector.auth === "oauth" ? "needs_sign_in" : connector.status,
          my_state: state,
        });
        toast(everyone ? `Everyone was signed out of ${connector.name}` : `Signed out of ${connector.name}`, "success");
      } catch (error) {
        toast(`Couldn't sign out: ${(error as Error).message}`, "error");
      } finally {
        mark(connector.id, false);
      }
    },
    [api, mark, toast, upsert],
  );

  const remove = useCallback(
    async (connector: Connector) => {
      mark(connector.id, true);
      try {
        await api.remove(connector.id);
        removeLocal(connector.id);
        toast(`${connector.name} removed`, "success");
        return true;
      } catch (error) {
        toast(`Couldn't remove ${connector.name}: ${(error as Error).message}`, "error");
        return false;
      } finally {
        mark(connector.id, false);
      }
    },
    [api, mark, removeLocal, toast],
  );

  const retry = useCallback(
    async (connector: Connector) => {
      mark(connector.id, true);
      try {
        const detail = await api.refreshTools(connector.id);
        upsert(detail);
        toast(
          detail.status === "unreachable"
            ? `Still can't reach ${connector.name}`
            : `${connector.name} is connected`,
          detail.status === "unreachable" ? "error" : "success",
        );
      } catch (error) {
        toast(`Couldn't retry ${connector.name}: ${(error as Error).message}`, "error");
      } finally {
        mark(connector.id, false);
      }
    },
    [api, mark, toast, upsert],
  );

  return {
    busyIds,
    isBusy: (id: string) => busyIds.has(id),
    toggleForMe,
    setEnabled,
    signIn,
    signOut,
    remove,
    retry,
  };
}

export type ConnectorActions = ReturnType<typeof useConnectorActions>;
