"use client";

import { KeyRound, Loader2, Trash2, X } from "lucide-react";
import { useCallback, useEffect, useId, useState } from "react";
import { getOrgSecrets, updateOrgSecrets, type OrgSecretsResponse } from "~/lib/api";
import { useToast } from "~/components/ui/toast";

export function AnthropicKeyForm({ onSaved }: { onSaved?: (value: OrgSecretsResponse) => void }) {
  const { toast } = useToast();
  const [status, setStatus] = useState<OrgSecretsResponse | null>(null);
  const [loading, setLoading] = useState(true);
  const [key, setKey] = useState("");
  const [saving, setSaving] = useState(false);
  const [loadError, setLoadError] = useState(false);
  const [readOnly, setReadOnly] = useState(false);
  const [confirmRemove, setConfirmRemove] = useState(false);
  const inputId = useId();

  const load = useCallback(async () => {
    setLoading(true);
    try {
      setStatus(await getOrgSecrets());
      setLoadError(false);
    } catch {
      setStatus(null);
      setLoadError(true);
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => { void load(); }, [load]);

  async function save() {
    if (!key.trim()) return;
    setSaving(true);
    try {
      const next = await updateOrgSecrets({ anthropic_api_key: key.trim() });
      setStatus(next);
      setKey("");
      setReadOnly(false);
      onSaved?.(next);
      toast(status?.has_key ? "anthropic key rotated" : "anthropic key saved", "success");
    } catch (error) {
      if (String(error).includes("403:")) {
        setReadOnly(true);
        toast("you do not have permission to update Team secrets", "error");
      } else toast(`failed to save key: ${error}`, "error");
    } finally {
      setSaving(false);
    }
  }

  async function remove() {
    setSaving(true);
    try {
      const next = await updateOrgSecrets({ anthropic_api_key: null });
      setStatus(next);
      setConfirmRemove(false);
      setReadOnly(false);
      onSaved?.(next);
      toast("anthropic key removed", "success");
    } catch (error) {
      if (String(error).includes("403:")) {
        setReadOnly(true);
        toast("you do not have permission to update Team secrets", "error");
      } else toast(`failed to remove key: ${error}`, "error");
    } finally {
      setSaving(false);
    }
  }

  if (loading) return <div className="flex items-center gap-2 p-5 text-xs text-[var(--color-text-dim)]"><Loader2 className="h-3 w-3 animate-spin" />checking key</div>;
  if (loadError) return <div className="flex items-center justify-between gap-3 p-5"><p className="text-xs text-[var(--color-error)]">Failed to load the Team key status.</p><button type="button" onClick={() => void load()} className="border border-[var(--color-border)] px-3 py-2 text-xs">Retry</button></div>;
  return (
    <div className="space-y-4 p-5">
      <div className="flex items-start justify-between gap-3">
        <div>
          <p className="text-[13px] font-medium text-[var(--color-text)]">{status?.has_key ? "key set" : "no key"}</p>
          <p className="mt-1 text-[11px] text-[var(--color-text-dim)]">
            {status?.has_key ? "Enter a new value only when you want to rotate it. The saved value is never displayed." : "Stored encrypted for this Team and never shown again."}
          </p>
          {status?.updated_at && <p className="mt-1 text-[11px] text-[var(--color-text-dim)]">Updated {new Date(status.updated_at * 1000).toLocaleString()}</p>}
          {readOnly && <p className="mt-1 text-[11px] text-[var(--color-warning)]">Write permission required.</p>}
        </div>
        {status?.has_key && (confirmRemove ? (
          <div className="flex items-center gap-1">
            <button type="button" onClick={() => void remove()} disabled={saving || readOnly} className="border border-[var(--color-error)]/40 px-3 py-1.5 text-xs text-[var(--color-error)] disabled:opacity-30">Confirm</button>
            <button type="button" onClick={() => setConfirmRemove(false)} aria-label="Cancel key removal" className="p-1.5 text-[var(--color-text-dim)]"><X className="h-3 w-3" /></button>
          </div>
        ) : (
          <button type="button" onClick={() => setConfirmRemove(true)} disabled={readOnly} className="flex items-center gap-1.5 border border-[var(--color-border)] px-3 py-1.5 text-xs text-[var(--color-text-dim)] disabled:opacity-30"><Trash2 className="h-3 w-3" />Remove</button>
        ))}
      </div>
      <div className="flex gap-2">
        <label htmlFor={inputId} className="sr-only">Anthropic API key</label>
        <input id={inputId} type="password" value={key} onChange={(event) => setKey(event.target.value)} onKeyDown={(event) => { if (event.key === "Enter") void save(); }} disabled={saving || readOnly} placeholder="sk-ant-..." autoComplete="off" className="min-w-0 flex-1 border border-[var(--color-border)] bg-[var(--color-bg-input)] px-3 py-2 text-xs font-mono outline-none disabled:opacity-40" />
        <button type="button" onClick={() => void save()} disabled={saving || readOnly || !key.trim()} className="flex items-center gap-2 bg-[var(--color-text)] px-4 py-2 text-xs text-[var(--color-bg)] disabled:opacity-30">
          {saving ? <Loader2 className="h-3 w-3 animate-spin" /> : <KeyRound className="h-3 w-3" />}
          {status?.has_key ? "rotate" : "save"}
        </button>
      </div>
    </div>
  );
}
