"use client";

import { ChevronDown, ShieldCheck, X } from "lucide-react";
import { useId, useState, type KeyboardEvent } from "react";
import type { OrgPolicy } from "~/lib/api/mcp-connectors";
import { Switch } from "~/components/ui/switch";
import { useToast } from "~/components/ui/toast";
import { useConnectors } from "./connectors-context";
import { Eyebrow, FOCUS_RING, TextInput } from "./ui";

/** One-line summary for the collapsed row: "Members can add personal connectors · any host". */
export function describePolicy(policy: OrgPolicy): string {
  const who = policy.allow_personal ? "Members can add personal connectors" : "Members can't add personal connectors";
  if (!policy.allow_personal) return who;
  const hosts =
    policy.allowed_hosts.length === 0
      ? "any host"
      : policy.allowed_hosts.length === 1
        ? policy.allowed_hosts[0]
        : `${policy.allowed_hosts.length} allowed hosts`;
  return `${who} · ${hosts}`;
}

/**
 * Admin-only, and secondary: a collapsed row below the lists that opens
 * into the two knobs the platform lead asked for (whether members may add
 * their own connectors, and which hosts those may reach). Every change
 * saves on the spot and says it applies to new chats.
 */
export function OrgPolicyCard({ policy, defaultOpen = false }: { policy: OrgPolicy; defaultOpen?: boolean }) {
  const { api, setPolicy } = useConnectors();
  const { toast } = useToast();
  const [open, setOpen] = useState(defaultOpen);
  const [saving, setSaving] = useState(false);
  const [draftHost, setDraftHost] = useState("");
  const switchId = useId();
  const inputId = useId();
  const bodyId = useId();

  const save = async (next: OrgPolicy) => {
    const previous = policy;
    setPolicy(next);
    setSaving(true);
    try {
      setPolicy(await api.updatePolicy(next));
      toast("Policy saved · applies to new chats", "success");
    } catch (error) {
      setPolicy(previous);
      toast(`Couldn't save the policy: ${(error as Error).message}`, "error");
    } finally {
      setSaving(false);
    }
  };

  const addHost = () => {
    const host = draftHost.trim().toLowerCase();
    if (!host) return;
    if (!/^[a-z0-9*.-]+$/.test(host)) {
      toast("Use a host name like mcp.example.com or *.example.com", "error");
      return;
    }
    if (policy.allowed_hosts.includes(host)) {
      setDraftHost("");
      return;
    }
    setDraftHost("");
    void save({ ...policy, allowed_hosts: [...policy.allowed_hosts, host] });
  };

  const onKey = (event: KeyboardEvent<HTMLInputElement>) => {
    if (event.key === "Enter") {
      event.preventDefault();
      addHost();
    }
  };

  return (
    <section
      aria-labelledby="org-policy-title"
      data-testid="org-policy-card"
      data-open={open}
      className="rounded-[var(--radius-card)] border border-[var(--color-border)] bg-[var(--color-bg-card)]"
    >
      <button
        type="button"
        aria-expanded={open}
        aria-controls={bodyId}
        data-testid="org-policy-toggle"
        onClick={() => setOpen((v) => !v)}
        className={`flex w-full items-center gap-3 rounded-[var(--radius-card)] px-4 py-3 text-left transition-colors hover:bg-[var(--color-bg-hover)] ${FOCUS_RING} focus-visible:ring-inset focus-visible:ring-offset-0`}
      >
        <span className="flex h-8 w-8 flex-none items-center justify-center rounded-[10px] border border-[var(--color-border)] bg-[var(--color-bg-elevated)]">
          <ShieldCheck className="h-4 w-4 text-[var(--color-text-muted)]" aria-hidden="true" />
        </span>
        <span className="min-w-0 flex-1">
          <Eyebrow>
            <span id="org-policy-title">Organization policy</span>
          </Eyebrow>
          <span className="mt-0.5 block truncate text-[12.5px] text-[var(--color-text)]" data-testid="org-policy-summary">
            {describePolicy(policy)}
          </span>
        </span>
        <ChevronDown
          className={`h-4 w-4 flex-none text-[var(--color-text-dim)] transition-transform ${open ? "rotate-180" : ""}`}
          aria-hidden="true"
        />
      </button>

      {open && (
        <div id={bodyId} className="border-t border-[var(--color-border)] px-4 pb-4 pt-3 sm:px-5">
          <p className="text-[12px] leading-5 text-[var(--color-text-dim)]">
            What members can add themselves. You can see every personal connector&apos;s address or
            command above, never its keys.
          </p>
          <div className="mt-3 divide-y divide-[var(--color-border)] rounded-[var(--radius-ctl)] border border-[var(--color-border)]">
            <div className="flex items-center gap-4 px-3.5 py-3">
              <div className="min-w-0 flex-1">
                <label htmlFor={switchId} className="block text-[12.5px] font-medium text-[var(--color-text)]">
                  Members can add personal connectors
                </label>
                <p className="text-[11.5px] text-[var(--color-text-dim)]">
                  Off hides the Personal section for everyone; the agent stops getting personal tools.
                </p>
              </div>
              <Switch
                id={switchId}
                checked={policy.allow_personal}
                busy={saving}
                data-testid="org-policy-allow-personal"
                onCheckedChange={(allow_personal) => void save({ ...policy, allow_personal })}
              />
            </div>
            <div className="px-3.5 py-3">
              <label htmlFor={inputId} className="block text-[12.5px] font-medium text-[var(--color-text)]">
                Hosts personal connectors may reach
              </label>
              <p className="text-[11.5px] text-[var(--color-text-dim)]">
                Empty means any public host. Add a host to restrict.
              </p>
              <div className="mt-2.5 flex flex-wrap items-center gap-1.5">
                {policy.allowed_hosts.map((host) => (
                  <span
                    key={host}
                    className="inline-flex h-7 items-center gap-1 rounded-full border border-[var(--color-border)] bg-[var(--color-bg-elevated)] pl-2.5 pr-1 font-mono text-[11.5px] text-[var(--color-text)]"
                  >
                    {host}
                    <button
                      type="button"
                      aria-label={`Remove ${host}`}
                      onClick={() =>
                        void save({ ...policy, allowed_hosts: policy.allowed_hosts.filter((h) => h !== host) })
                      }
                      className={`flex h-5 w-5 items-center justify-center rounded-full text-[var(--color-text-dim)] hover:bg-[var(--color-bg-hover)] hover:text-[var(--color-text)] ${FOCUS_RING}`}
                    >
                      <X className="h-3 w-3" aria-hidden="true" />
                    </button>
                  </span>
                ))}
                <div className="min-w-[220px] flex-1">
                  <TextInput
                    id={inputId}
                    mono
                    value={draftHost}
                    placeholder="mcp.example.com · press Enter"
                    onChange={(e) => setDraftHost(e.target.value)}
                    onKeyDown={onKey}
                    onBlur={addHost}
                    data-testid="org-policy-host-input"
                    className="min-h-[32px] text-[12px]"
                  />
                </div>
              </div>
            </div>
          </div>
        </div>
      )}
    </section>
  );
}
