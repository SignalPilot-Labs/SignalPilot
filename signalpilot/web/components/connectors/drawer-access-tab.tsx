"use client";

import { AlertTriangle, KeyRound, LogIn, LogOut, ShieldAlert, UserRound } from "lucide-react";
import { useState } from "react";
import type { ConnectorDetail } from "~/lib/api/mcp-connectors";
import { ConfirmDialog } from "~/components/ui/confirm-dialog";
import { useToast } from "~/components/ui/toast";
import { useConnectors } from "./connectors-context";
import { Button, Chip, Eyebrow, Field, Notice, TextInput, timeAgo } from "./ui";
import type { ConnectorActions } from "./use-connector-actions";

type SecretKind = "header" | "env";

/** One write-only secret: masked with its saved state, Replace inline. */
function SecretRow({
  kind,
  name,
  hasValue,
  memberSupplied,
  savedAt,
  canEdit,
  onSave,
}: {
  kind: SecretKind;
  name: string;
  hasValue: boolean;
  memberSupplied: boolean;
  savedAt: string;
  canEdit: boolean;
  onSave: (value: string) => Promise<void>;
}) {
  const [editing, setEditing] = useState(!hasValue && canEdit);
  const [value, setValue] = useState("");
  const [saving, setSaving] = useState(false);
  const submit = async () => {
    if (!value) return;
    setSaving(true);
    try {
      await onSave(value);
      setValue("");
      setEditing(false);
    } finally {
      setSaving(false);
    }
  };
  return (
    <li
      data-testid="secret-row"
      data-secret={name}
      className={`px-3.5 py-3 ${memberSupplied ? "bg-[var(--color-success)]/[0.03]" : ""}`}
    >
      <div className="flex flex-wrap items-center gap-x-3 gap-y-1.5">
        <span className="font-mono text-[12.5px] text-[var(--color-text)]">{name}</span>
        <Chip>{kind === "header" ? "Header" : "Environment"}</Chip>
        {memberSupplied && <Chip tone="read">Yours</Chip>}
        <span className="ml-auto text-[11.5px] text-[var(--color-text-dim)]">
          {hasValue ? (
            <>
              <span className="font-mono tracking-[0.2em]">••••••</span> saved {timeAgo(savedAt)}
            </>
          ) : (
            "not set"
          )}
        </span>
        {canEdit && !editing && (
          <Button onClick={() => setEditing(true)} data-testid="secret-replace" className="min-h-[30px] px-2.5 text-[11.5px]">
            {hasValue ? "Replace" : "Add key"}
          </Button>
        )}
      </div>
      {editing && (
        <div className="mt-2.5 flex items-end gap-2">
          <div className="flex-1">
            <Field label={hasValue ? "New key" : "Key"} hint={hasValue ? "The old key is discarded." : "Saved encrypted. Never shown again."} htmlFor={`secret-${name}`}>
              <TextInput
                id={`secret-${name}`}
                mono
                type="password"
                autoComplete="off"
                autoFocus
                value={value}
                data-testid="secret-input"
                onChange={(e) => setValue(e.target.value)}
                onKeyDown={(e) => e.key === "Enter" && void submit()}
              />
            </Field>
          </div>
          <Button variant="primary" pending={saving} disabled={!value} onClick={() => void submit()} data-testid="secret-save" className="mb-[26px]">
            Save
          </Button>
          {hasValue && (
            <Button variant="ghost" onClick={() => setEditing(false)} className="mb-[26px]">
              Cancel
            </Button>
          )}
        </div>
      )}
    </li>
  );
}

/**
 * Access tab: the sign-in state (and Sign in / Sign out), then keys. Member-
 * supplied fields on org connectors are highlighted. Admins get "Sign
 * everyone out". Sandbox connectors carry the honest label.
 */
export function DrawerAccessTab({
  detail,
  isAdmin,
  actions,
  onDetail,
}: {
  detail: ConnectorDetail;
  isAdmin: boolean;
  actions: ConnectorActions;
  onDetail: (next: ConnectorDetail) => void;
}) {
  const { api } = useConnectors();
  const { toast } = useToast();
  const [confirmEveryone, setConfirmEveryone] = useState(false);
  const me = detail.my_state;
  const canManage = detail.scope === "personal" || isAdmin;
  const busy = actions.isBusy(detail.id);

  const saveSecret = (kind: SecretKind, name: string) => async (value: string) => {
    try {
      const updated = await api.updateSecrets(detail.id, { [kind === "header" ? "headers" : "env"]: { [name]: value } });
      onDetail({ ...detail, ...updated, tools: detail.tools });
      toast(`${name} saved · applies to new chats`, "success");
    } catch (error) {
      toast(`Couldn't save ${name}: ${(error as Error).message}`, "error");
      throw error;
    }
  };

  const secrets = [
    ...detail.header_keys.map((key) => ({ kind: "header" as const, name: key.name, hasValue: key.has_value, memberSupplied: false })),
    ...detail.env_keys
      .filter((key) => key.secret || key.member_supplied)
      .map((key) => ({
        kind: "env" as const,
        name: key.name,
        hasValue: key.member_supplied ? Boolean(me?.has_key) : key.has_value,
        memberSupplied: key.member_supplied,
      })),
  ];

  return (
    <div className="space-y-6">
      {detail.transport === "stdio" && (
        <Notice tone="warning" testId="drawer-access-sandbox" icon={<ShieldAlert className="h-3.5 w-3.5" aria-hidden="true" />}>
          Runs inside your sandbox. The agent can read this server&apos;s settings, including any keys.
        </Notice>
      )}

      {detail.auth === "oauth" && (
        <section aria-labelledby="access-sign-in">
          <Eyebrow className="mb-2">
            <span id="access-sign-in">Sign-in</span>
          </Eyebrow>
          <div className="flex flex-wrap items-center gap-3 rounded-[var(--radius-card)] border border-[var(--color-border)] bg-[var(--color-bg-card)] px-4 py-3.5">
            <span className={`flex h-9 w-9 flex-none items-center justify-center rounded-[10px] border ${me?.signed_in ? "border-[var(--color-success)]/30 bg-[var(--color-success)]/10 text-[var(--color-success)]" : "border-[var(--color-warning)]/30 bg-[var(--color-warning)]/10 text-[var(--color-warning)]"}`}>
              <UserRound className="h-4 w-4" aria-hidden="true" />
            </span>
            <div className="min-w-0 flex-1">
              <p className="text-[13px] font-medium text-[var(--color-text)]" data-testid="drawer-access-sign-in-state">
                {me?.signed_in ? "Signed in" : "Needs sign-in"}
                {me?.signed_in && me.account_label && (
                  <span className="font-normal text-[var(--color-text-muted)]" data-testid="drawer-access-account">
                    {" "}as <span className="font-mono text-[12px]">{me.account_label}</span>
                  </span>
                )}
              </p>
              <p className="text-[11.5px] text-[var(--color-text-dim)]">
                {me?.signed_in
                  ? `Since ${timeAgo(me.signed_in_at)}. The agent acts as you on ${detail.name}.`
                  : detail.scope === "org"
                    ? "Each member signs in with their own account."
                    : "The agent can't use this until you sign in."}
              </p>
            </div>
            {me?.signed_in ? (
              <Button pending={busy} onClick={() => void actions.signOut(detail)} data-testid="drawer-access-sign-out">
                <LogOut className="h-3.5 w-3.5" aria-hidden="true" />
                Sign out
              </Button>
            ) : (
              <Button variant="primary" pending={busy} onClick={() => void actions.signIn(detail)} data-testid="drawer-access-sign-in">
                <LogIn className="h-3.5 w-3.5" aria-hidden="true" />
                Sign in
              </Button>
            )}
          </div>
          {detail.scope === "org" && isAdmin && (
            <div className="mt-2 flex items-center justify-between gap-3 px-1">
              <p className="text-[11.5px] text-[var(--color-text-dim)]" data-testid="drawer-access-signed-in-count">
                {typeof detail.signed_in_count === "number"
                  ? detail.signed_in_count === 0
                    ? "No one has signed in yet."
                    : `${detail.signed_in_count} ${detail.signed_in_count === 1 ? "member is" : "members are"} signed in.`
                  : ""}{" "}
                Signing everyone out means each member signs in again before the agent can use it.
              </p>
              <Button variant="ghost" onClick={() => setConfirmEveryone(true)} data-testid="drawer-access-sign-everyone-out" className="min-h-[32px] text-[12px] text-[var(--color-error)]">
                Sign everyone out
              </Button>
            </div>
          )}
        </section>
      )}

      <section aria-labelledby="access-keys">
        <Eyebrow className="mb-2">
          <span id="access-keys">Keys</span>
        </Eyebrow>
        {secrets.length === 0 ? (
          <p className="rounded-[var(--radius-card)] border border-dashed border-[var(--color-border)] px-4 py-4 text-[12.5px] text-[var(--color-text-dim)]">
            {detail.auth === "oauth" ? "No keys. Sign-in covers access." : "This connector doesn't use a key."}
          </p>
        ) : (
          <ul className="divide-y divide-[var(--color-border)] rounded-[var(--radius-card)] border border-[var(--color-border)] bg-[var(--color-bg-card)]">
            {secrets.map((secret) => (
              <SecretRow
                key={`${secret.kind}:${secret.name}`}
                kind={secret.kind}
                name={secret.name}
                hasValue={secret.hasValue}
                memberSupplied={secret.memberSupplied}
                savedAt={detail.updated_at}
                canEdit={secret.memberSupplied || canManage}
                onSave={saveSecret(secret.kind, secret.name)}
              />
            ))}
          </ul>
        )}
        {detail.scope === "org" && secrets.some((s) => !s.memberSupplied) && isAdmin && (
          <p className="mt-2 flex items-start gap-1.5 px-1 text-[11.5px] text-[var(--color-text-dim)]">
            <KeyRound className="mt-0.5 h-3 w-3 flex-none" aria-hidden="true" />
            Members use the shared key. The provider&apos;s logs will show your account.
          </p>
        )}
        {detail.transport === "stdio" && (
          <p className="mt-2 flex items-start gap-1.5 px-1 text-[11.5px] text-[var(--color-text-dim)]" data-testid="drawer-access-sandbox-notes">
            <AlertTriangle className="mt-0.5 h-3 w-3 flex-none" aria-hidden="true" />
            <span>
              Tool switches are enforced by the agent&apos;s tool permissions, not by SignalPilot. If this server
              calls the internet, the host must be allowed by your deployment.
            </span>
          </p>
        )}
      </section>

      <ConfirmDialog
        open={confirmEveryone}
        title={`Sign everyone out of ${detail.name}?`}
        message="Every member will need to sign in again before the agent can use it."
        confirmLabel="Sign everyone out"
        cancelLabel="Cancel"
        onCancel={() => setConfirmEveryone(false)}
        onConfirm={() => {
          setConfirmEveryone(false);
          void actions.signOut(detail, true);
        }}
      />
    </div>
  );
}
