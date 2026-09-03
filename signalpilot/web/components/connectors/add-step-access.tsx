"use client";

import { Check, KeyRound, LogIn, Plus, Trash2, Unlock } from "lucide-react";
import { useId, useState } from "react";
import { GATEWAY_URL } from "~/lib/api/client";
import type { ServerInput } from "~/lib/mcp-connectors-state";
import { CopyButton } from "~/components/ui/copy-button";
import type { AccessKind, AddFlowState, EnvRow } from "./add-flow-state";
import { Field, FOCUS_RING, Notice, TextInput } from "./ui";

const OPTIONS: { value: AccessKind; label: string; hint: string; icon: typeof LogIn }[] = [
  { value: "none", label: "No sign-in", hint: "The server is open, or needs nothing from you.", icon: Unlock },
  { value: "oauth", label: "Sign in", hint: "A normal sign-in window. Each person signs in as themselves.", icon: LogIn },
  { value: "key", label: "Key", hint: "A key or header value from the provider.", icon: KeyRound },
];

/**
 * Step 2 — access. Pre-selected from the probe; the user can override it.
 * Keys are write-only from here on. For sign-in, the window opens after the
 * connector exists, so this step only collects a registered client when the
 * provider insists on one, and shows the redirect address admins will need.
 */
export function AddStepAccess({
  state,
  input,
  onChange,
}: {
  state: AddFlowState;
  input: ServerInput;
  onChange: (patch: Partial<AddFlowState>) => void;
}) {
  const groupId = useId();
  const remote = input.kind === "url";
  const manual = state.probe?.oauth?.registration === "manual";
  const [showClient, setShowClient] = useState(manual);
  const redirectUri = `${GATEWAY_URL}/api/mcp/oauth/callback`;

  return (
    <div className="space-y-5">
      <div role="radiogroup" aria-labelledby={groupId} className="space-y-2">
        <p id={groupId} className="text-[12px] font-medium text-[var(--color-text-muted)]">
          How the agent gets access
          {state.probe && !state.probe.error && (
            <span className="ml-2 font-normal text-[var(--color-text-dim)]">
              · detected from the server
            </span>
          )}
        </p>
        {/* Commands: no provider sign-in, and the env editor below is the key. */}
        {OPTIONS.filter((option) => remote || option.value === "none").map((option) => {
          const active = state.access === option.value;
          const Icon = option.icon;
          return (
            <button
              key={option.value}
              type="button"
              role="radio"
              aria-checked={active}
              data-testid={`add-access-${option.value}`}
              onClick={() => onChange({ access: option.value })}
              className={`flex w-full items-center gap-3 rounded-[var(--radius-ctl)] border px-3.5 py-3 text-left transition-colors ${FOCUS_RING} ${
                active
                  ? "border-[var(--color-border-active)] bg-[var(--color-bg-hover)]"
                  : "border-[var(--color-border)] bg-[var(--color-bg-card)] hover:border-[var(--color-border-hover)]"
              }`}
            >
              <span
                className={`flex h-8 w-8 flex-none items-center justify-center rounded-[8px] border ${
                  active
                    ? "border-[var(--color-success)]/40 bg-[var(--color-success)]/10 text-[var(--color-success)]"
                    : "border-[var(--color-border)] text-[var(--color-text-dim)]"
                }`}
              >
                <Icon className="h-3.5 w-3.5" aria-hidden="true" />
              </span>
              <span className="min-w-0 flex-1">
                <span className="block text-[13px] font-medium text-[var(--color-text)]">{option.label}</span>
                <span className="block text-[11.5px] text-[var(--color-text-dim)]">{option.hint}</span>
              </span>
              {active && <Check className="h-4 w-4 flex-none text-[var(--color-success)]" aria-hidden="true" />}
            </button>
          );
        })}
      </div>

      {state.access === "key" && remote && (
        <div className="space-y-3 rounded-[var(--radius-card)] border border-[var(--color-border)] bg-[var(--color-bg-card)] p-4">
          <div className="grid gap-3 sm:grid-cols-[180px_1fr]">
            <Field label="Header" htmlFor="add-header-name">
              <TextInput
                id="add-header-name"
                mono
                value={state.headerName}
                onChange={(e) => onChange({ headerName: e.target.value })}
                placeholder="Authorization"
              />
            </Field>
            <Field
              label="Key"
              htmlFor="add-header-value"
              hint={state.memberSupplied ? "Each member enters their own key from Access." : "Saved encrypted. Never shown again after this."}
            >
              <TextInput
                id="add-header-value"
                mono
                type="password"
                autoComplete="off"
                disabled={state.memberSupplied}
                value={state.headerValue}
                data-testid="add-key-value"
                onChange={(e) => onChange({ headerValue: e.target.value })}
                placeholder={state.memberSupplied ? "Provided by each member" : "Bearer …"}
              />
            </Field>
          </div>
          {state.scope === "org" && (
            <label className="flex cursor-pointer items-start gap-2.5 text-[12px] text-[var(--color-text-muted)]">
              <input
                type="checkbox"
                checked={state.memberSupplied}
                onChange={(e) => onChange({ memberSupplied: e.target.checked, headerValue: "" })}
                className="mt-0.5 h-3.5 w-3.5 accent-[var(--color-success)]"
              />
              <span>
                Each member provides their own key.
                <span className="block text-[var(--color-text-dim)]">
                  Off: members will use the key you enter here, and the provider&apos;s logs will show your account.
                </span>
              </span>
            </label>
          )}
        </div>
      )}

      {input.kind === "command" && (
        <EnvEditor
          rows={state.env}
          orgScope={state.scope === "org"}
          onChange={(env) => onChange({ env })}
        />
      )}

      {state.access === "oauth" && (
        <div className="space-y-3">
          <Notice tone="info" icon={<LogIn className="h-3.5 w-3.5" aria-hidden="true" />}>
            You&apos;ll sign in right after connecting, in a normal sign-in window.
            {state.scope === "org" && " Each member signs in with their own account."}
          </Notice>
          {manual ? (
            <p className="text-[12px] text-[var(--color-text-muted)]">
              This provider needs a registered client. Your provider&apos;s docs will have these values.
            </p>
          ) : (
            <button
              type="button"
              onClick={() => setShowClient((v) => !v)}
              aria-expanded={showClient}
              className={`text-[12px] text-[var(--color-text-dim)] underline decoration-[var(--color-border-hover)] underline-offset-4 hover:text-[var(--color-text)] ${FOCUS_RING}`}
            >
              {showClient ? "Hide registered client" : "Provider needs a registered client?"}
            </button>
          )}
          {showClient && (
            <div className="space-y-3 rounded-[var(--radius-card)] border border-[var(--color-border)] bg-[var(--color-bg-card)] p-4">
              <div className="grid gap-3 sm:grid-cols-2">
                <Field label="Client ID" htmlFor="add-client-id">
                  <TextInput
                    id="add-client-id"
                    mono
                    value={state.clientId}
                    onChange={(e) => onChange({ clientId: e.target.value })}
                  />
                </Field>
                <Field label="Client secret" htmlFor="add-client-secret" hint="Optional. Saved encrypted.">
                  <TextInput
                    id="add-client-secret"
                    mono
                    type="password"
                    autoComplete="off"
                    value={state.clientSecret}
                    onChange={(e) => onChange({ clientSecret: e.target.value })}
                  />
                </Field>
              </div>
              <div>
                <p className="text-[12px] font-medium text-[var(--color-text-muted)]">Redirect address to register</p>
                <div className="mt-1.5 flex items-center gap-2">
                  <code className="min-w-0 flex-1 truncate rounded-[8px] border border-[var(--color-border)] bg-[var(--color-bg-input)] px-2.5 py-1.5 text-[11.5px] text-[var(--color-text)]">
                    {redirectUri}
                  </code>
                  <CopyButton text={redirectUri} label="copy" />
                </div>
                <p className="mt-1 text-[11.5px] text-[var(--color-text-dim)]">
                  It differs per environment. Register the one for where you&apos;re signed in now.
                </p>
              </div>
            </div>
          )}
        </div>
      )}
    </div>
  );
}

function EnvEditor({
  rows,
  orgScope,
  onChange,
}: {
  rows: EnvRow[];
  orgScope: boolean;
  onChange: (rows: EnvRow[]) => void;
}) {
  const update = (index: number, patch: Partial<EnvRow>) =>
    onChange(rows.map((row, i) => (i === index ? { ...row, ...patch } : row)));
  return (
    <div className="space-y-2.5 rounded-[var(--radius-card)] border border-[var(--color-border)] bg-[var(--color-bg-card)] p-4">
      <div className="flex items-center justify-between">
        <p className="text-[12px] font-medium text-[var(--color-text-muted)]">Environment variables</p>
        <button
          type="button"
          data-testid="add-env-add"
          onClick={() =>
            onChange([...rows, { name: "", value: "", secret: true, member_supplied: orgScope }])
          }
          className={`inline-flex h-7 items-center gap-1 rounded-[6px] px-2 text-[11.5px] text-[var(--color-text-muted)] hover:bg-[var(--color-bg-hover)] hover:text-[var(--color-text)] ${FOCUS_RING}`}
        >
          <Plus className="h-3 w-3" aria-hidden="true" />
          Add variable
        </button>
      </div>
      {rows.length === 0 && (
        <p className="text-[11.5px] text-[var(--color-text-dim)]">
          None needed, or add the token the server expects. Values are secret by default.
        </p>
      )}
      {rows.map((row, index) => (
        // Below lg the modal is too narrow for three columns; the name is the
        // column that must never truncate, so the row stacks instead.
        <div key={index} className="grid gap-2 lg:grid-cols-[minmax(0,1.8fr)_minmax(0,1fr)_auto]">
          <TextInput
            mono
            aria-label="Variable name"
            placeholder="GITHUB_PERSONAL_ACCESS_TOKEN"
            value={row.name}
            data-testid="add-env-name"
            className="!text-[12px]"
            onChange={(e) => update(index, { name: e.target.value.toUpperCase().replace(/[^A-Z0-9_]/g, "_") })}
          />
          <TextInput
            mono
            aria-label="Value"
            type={row.secret ? "password" : "text"}
            autoComplete="off"
            disabled={row.member_supplied}
            placeholder={row.member_supplied ? "Each member enters their own" : "value"}
            value={row.value}
            data-testid="add-env-value"
            className="!text-[12px]"
            onChange={(e) => update(index, { value: e.target.value })}
          />
          <div className="flex items-center gap-2">
            {orgScope ? (
              <label className="flex items-center gap-1.5 text-[11px] text-[var(--color-text-dim)]">
                <input
                  type="checkbox"
                  checked={row.member_supplied}
                  onChange={(e) => update(index, { member_supplied: e.target.checked, value: "" })}
                  className="h-3.5 w-3.5 accent-[var(--color-success)]"
                />
                per member
              </label>
            ) : (
              <label className="flex items-center gap-1.5 text-[11px] text-[var(--color-text-dim)]">
                <input
                  type="checkbox"
                  checked={row.secret}
                  onChange={(e) => update(index, { secret: e.target.checked })}
                  className="h-3.5 w-3.5 accent-[var(--color-success)]"
                />
                secret
              </label>
            )}
            <button
              type="button"
              aria-label="Remove variable"
              onClick={() => onChange(rows.filter((_, i) => i !== index))}
              className={`flex h-9 w-9 items-center justify-center rounded-[8px] text-[var(--color-text-dim)] hover:bg-[var(--color-bg-hover)] hover:text-[var(--color-error)] ${FOCUS_RING}`}
            >
              <Trash2 className="h-3.5 w-3.5" aria-hidden="true" />
            </button>
          </div>
        </div>
      ))}
      {orgScope && rows.some((r) => r.secret && !r.member_supplied) && (
        <p className="text-[11.5px] text-[var(--color-warning)]">
          Org sandbox connectors can&apos;t carry a shared secret: every member would be able to read it. Mark secrets as per member.
        </p>
      )}
    </div>
  );
}
