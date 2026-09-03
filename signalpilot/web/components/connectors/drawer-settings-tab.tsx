"use client";

import { Lock, Trash2 } from "lucide-react";
import { useEffect, useId, useState } from "react";
import type { ConnectorDetail } from "~/lib/api/mcp-connectors";
import { splitCommand } from "~/lib/mcp-connectors-state";
import { CopyButton } from "~/components/ui/copy-button";
import { Switch } from "~/components/ui/switch";
import { useToast } from "~/components/ui/toast";
import { useConnectors } from "./connectors-context";
import { Button, Chip, Eyebrow, Field, TextInput, timeAgo } from "./ui";
import type { ConnectorActions } from "./use-connector-actions";

const CURRENT_PROTOCOL = "2025-06-18";

/**
 * Settings tab: name, address or command, scope, the enable switch, how
 * the agent sees it, and Remove. Members of an org connector read this
 * tab as plain rows ("Managed by your admin"); nothing looks editable.
 */
export function DrawerSettingsTab({
  detail,
  isAdmin,
  actions,
  onDetail,
  onRemove,
}: {
  detail: ConnectorDetail;
  isAdmin: boolean;
  actions: ConnectorActions;
  onDetail: (next: ConnectorDetail) => void;
  onRemove: () => void;
}) {
  const { api, orgName } = useConnectors();
  const { toast } = useToast();
  const canManage = detail.scope === "personal" || isAdmin;
  const targetValue = detail.url ?? [detail.command, ...detail.args].filter(Boolean).join(" ");
  const [name, setName] = useState(detail.name);
  const [target, setTarget] = useState(targetValue);
  const [saving, setSaving] = useState(false);
  const nameId = useId();
  const targetId = useId();
  const enabledId = useId();

  useEffect(() => {
    setName(detail.name);
    setTarget(detail.url ?? [detail.command, ...detail.args].filter(Boolean).join(" "));
  }, [detail.id, detail.name, detail.url, detail.command, detail.args]);

  const dirty = name.trim() !== detail.name || target.trim() !== targetValue;

  const save = async () => {
    setSaving(true);
    try {
      const body: Parameters<typeof api.patch>[1] = { name: name.trim() };
      if (detail.transport === "stdio") {
        const parts = splitCommand(target);
        body.command = parts[0] ?? "";
        body.args = parts.slice(1);
      } else {
        body.url = target.trim();
      }
      const updated = await api.patch(detail.id, body);
      onDetail({ ...detail, ...updated, tools: detail.tools });
      toast("Saved · applies to new chats", "success");
    } catch (error) {
      toast(`Couldn't save: ${(error as Error).message}`, "error");
    } finally {
      setSaving(false);
    }
  };

  const older = detail.protocol_version && detail.protocol_version < CURRENT_PROTOCOL;
  const targetLabel = detail.transport === "stdio" ? "Command" : "Address";
  const everyone = orgName ? `Everyone in ${orgName}` : "Everyone in your organization";

  return (
    <div className="space-y-6">
      {canManage ? (
        <section className="space-y-4">
          <Field label="Name" htmlFor={nameId}>
            <TextInput id={nameId} value={name} onChange={(e) => setName(e.target.value)} data-testid="drawer-settings-name" />
          </Field>
          <Field
            label={targetLabel}
            htmlFor={targetId}
            hint={detail.transport === "stdio" ? "Runs inside the sandbox when a chat starts." : "Reached through SignalPilot, never directly from the sandbox."}
          >
            <TextInput id={targetId} mono value={target} onChange={(e) => setTarget(e.target.value)} data-testid="drawer-settings-target" />
          </Field>
          <div className="flex items-center justify-between gap-3">
            <p className="text-[11.5px] text-[var(--color-text-dim)]">
              {dirty ? "Unsaved changes. The connector is checked again after saving." : `Updated ${timeAgo(detail.updated_at)}`}
            </p>
            <Button variant="primary" pending={saving} disabled={!dirty || !name.trim()} onClick={() => void save()} data-testid="drawer-settings-save">
              Save
            </Button>
          </div>
        </section>
      ) : (
        <section className="rounded-[var(--radius-card)] border border-[var(--color-border)] bg-[var(--color-bg-card)]" data-testid="drawer-settings-readonly">
          <p className="flex items-center gap-1.5 border-b border-[var(--color-border)] px-4 py-2.5 text-[11.5px] text-[var(--color-text-dim)]">
            <Lock className="h-3 w-3" aria-hidden="true" />
            Managed by your admin
          </p>
          <dl className="grid grid-cols-[100px_1fr] gap-x-4 gap-y-2 px-4 py-3.5 text-[12px]">
            <dt className="text-[var(--color-text-dim)]">Name</dt>
            <dd className="text-[var(--color-text)]" data-testid="drawer-settings-name">{detail.name}</dd>
            <dt className="text-[var(--color-text-dim)]">{targetLabel}</dt>
            <dd className="break-all font-mono text-[11.5px] text-[var(--color-text)]" data-testid="drawer-settings-target">{targetValue}</dd>
          </dl>
        </section>
      )}

      <section className="rounded-[var(--radius-card)] border border-[var(--color-border)] bg-[var(--color-bg-card)]">
        {canManage ? (
          <div className="flex items-center gap-4 px-4 py-3.5">
            <div className="min-w-0 flex-1">
              <label htmlFor={enabledId} className="block text-[13px] font-medium text-[var(--color-text)]">
                {detail.scope === "org" ? "On for everyone" : "On"}
              </label>
              <p className="text-[11.5px] text-[var(--color-text-dim)]">
                {detail.enabled
                  ? detail.scope === "org"
                    ? "Turning off keeps members' sign-ins. Chats in progress lose access now."
                    : "Turning off keeps your settings and sign-in."
                  : detail.scope === "org"
                    ? "Turned off by your organization."
                    : "Turned off."}
              </p>
            </div>
            <Switch
              id={enabledId}
              checked={detail.enabled}
              busy={actions.isBusy(detail.id)}
              data-testid="drawer-settings-enabled"
              onCheckedChange={(enabled) => void actions.setEnabled(detail, enabled)}
            />
          </div>
        ) : (
          <div className="flex items-center gap-4 px-4 py-3.5">
            <div className="min-w-0 flex-1">
              <p className="text-[13px] font-medium text-[var(--color-text)]">{detail.enabled ? "On for everyone" : "Off for everyone"}</p>
              <p className="text-[11.5px] text-[var(--color-text-dim)]">
                {detail.enabled ? "Your admin turned this on. Use the switch on its row to turn it off for yourself." : "Turned off by your organization."}
              </p>
            </div>
            <Chip tone={detail.enabled ? "read" : "neutral"}>{detail.enabled ? "On" : "Off"}</Chip>
          </div>
        )}
        <dl className="grid grid-cols-[120px_1fr] gap-x-4 gap-y-2 border-t border-[var(--color-border)] px-4 py-3.5 text-[12px]">
          <dt className="text-[var(--color-text-dim)]">Who can use it</dt>
          <dd>
            <Chip testId="drawer-settings-scope">{detail.scope === "org" ? everyone : "Only you"}</Chip>
          </dd>
          <dt className="text-[var(--color-text-dim)]">Agent sees it as</dt>
          <dd className="flex items-center gap-2">
            <code className="font-mono text-[11.5px] text-[var(--color-text)]" data-testid="drawer-settings-slug">
              mcp__{detail.slug}__&lt;tool&gt;
            </code>
            <CopyButton text={`mcp__${detail.slug}__`} label="copy" />
          </dd>
          {detail.server_name && (
            <>
              <dt className="text-[var(--color-text-dim)]">Server calls itself</dt>
              <dd className="font-mono text-[11.5px] text-[var(--color-text-muted)]">{detail.server_name}</dd>
            </>
          )}
          {detail.protocol_version && (
            <>
              <dt className="text-[var(--color-text-dim)]">Protocol</dt>
              <dd className="flex items-center gap-2 font-mono text-[11.5px] text-[var(--color-text-muted)]">
                {detail.protocol_version}
                {older && <Chip tone="write">Older protocol</Chip>}
              </dd>
            </>
          )}
          <dt className="text-[var(--color-text-dim)]">Added</dt>
          <dd className="text-[var(--color-text-muted)]">{timeAgo(detail.created_at)}</dd>
          <dt className="text-[var(--color-text-dim)]">Last used</dt>
          <dd className="text-[var(--color-text-muted)]">{timeAgo(detail.last_used_at)}</dd>
        </dl>
      </section>

      {canManage && (
        <section className="rounded-[var(--radius-card)] border border-[var(--color-error)]/25 px-4 py-3.5">
          <Eyebrow className="text-[var(--color-error)]">Remove</Eyebrow>
          <div className="mt-1.5 flex flex-wrap items-center justify-between gap-3">
            <p className="max-w-sm text-[12px] leading-5 text-[var(--color-text-muted)]">
              {detail.scope === "org"
                ? "The agent loses its tools for everyone. Members' sign-ins and keys are deleted."
                : "The agent loses its tools. Your saved keys are deleted."}
              {detail.auth === "oauth" && " You'll be signed out of it."}
            </p>
            <Button variant="danger" onClick={onRemove} data-testid="drawer-settings-remove">
              <Trash2 className="h-3.5 w-3.5" aria-hidden="true" />
              Remove…
            </Button>
          </div>
        </section>
      )}
    </div>
  );
}
