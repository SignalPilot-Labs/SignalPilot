"use client";

import { useState } from "react";
import { Key, Loader2 } from "lucide-react";
import type { ApiKeyCreatedResponse } from "~/lib/backend-client";
import { ALL_SCOPES } from "~/lib/api-key-scopes";

// ---------------------------------------------------------------------------
// Create key form (inline)
// ---------------------------------------------------------------------------

export function CreateKeyForm({
  onCreated,
  onCancel,
  createFn,
}: {
  onCreated: (key: ApiKeyCreatedResponse) => void;
  onCancel: () => void;
  createFn: (name: string, scopes: string[]) => Promise<ApiKeyCreatedResponse>;
}) {
  const [name, setName] = useState("");
  const [scopes, setScopes] = useState<string[]>(["read", "query"]);
  const [creating, setCreating] = useState(false);
  const [error, setError] = useState<string | null>(null);

  function toggleScope(scope: string) {
    setScopes((prev) =>
      prev.includes(scope) ? prev.filter((s) => s !== scope) : [...prev, scope],
    );
  }

  async function handleCreate() {
    if (!name.trim()) {
      setError("key name is required");
      return;
    }
    if (scopes.length === 0) {
      setError("select at least one scope");
      return;
    }
    setCreating(true);
    setError(null);
    try {
      const created = await createFn(name.trim(), scopes);
      onCreated(created);
    } catch (e) {
      setError(String(e));
    } finally {
      setCreating(false);
    }
  }

  return (
    <div className="border border-[var(--color-border)] bg-[var(--color-bg-card)] rounded-[14px] p-5 animate-fade-in">
      <div className="space-y-4">
        {/* Name input */}
        <div>
          <label className="block text-[12px] text-[var(--color-text-dim)] mb-1.5">
            key name
          </label>
          <input
            type="text"
            value={name}
            onChange={(e) => setName(e.target.value)}
            onKeyDown={(e) => {
              if (e.key === "Enter") handleCreate();
              if (e.key === "Escape") onCancel();
            }}
            placeholder="e.g. production, ci-pipeline, local-dev"
            autoFocus
            className="w-full px-3 py-2 bg-[var(--color-bg-input)] border border-[var(--color-border)] rounded-[10px] text-xs focus:outline-none focus:border-[var(--color-text-dim)]"
          />
        </div>

        {/* Scopes */}
        <div>
          <label className="block text-[12px] text-[var(--color-text-dim)] mb-2">
            scopes
          </label>
          <div className="grid grid-cols-2 gap-2">
            {ALL_SCOPES.map((s) => {
              const checked = scopes.includes(s.value);
              return (
                <label
                  key={s.value}
                  className={`flex items-start gap-2.5 px-3 py-2.5 border rounded-[10px] cursor-pointer transition-colors duration-150 ${
                    checked
                      ? "border-[var(--color-success)]/40 bg-[var(--color-success)]/5"
                      : "border-[var(--color-border)] hover:border-[var(--color-border-hover)]"
                  }`}
                >
                  <input
                    type="checkbox"
                    checked={checked}
                    onChange={() => toggleScope(s.value)}
                    className="mt-0.5 accent-[var(--color-success)]"
                  />
                  <div>
                    <span className="text-[12px] text-[var(--color-text-muted)]">
                      {s.label}
                    </span>
                    <p className="text-[11px] text-[var(--color-text-dim)] mt-0.5">
                      {s.description}
                    </p>
                  </div>
                </label>
              );
            })}
          </div>
        </div>

        {/* Error */}
        {error && (
          <p className="text-[12px] text-[var(--color-error)]">{error}</p>
        )}

        {/* Actions */}
        <div className="flex items-center gap-3 pt-1">
          <button
            onClick={handleCreate}
            disabled={creating || !name.trim()}
            className="flex items-center gap-2 px-4 py-2 bg-[var(--color-text)] text-[var(--color-bg)] text-xs rounded-[10px] transition-opacity duration-150 hover:opacity-90 disabled:opacity-30"
          >
            {creating ? (
              <Loader2 className="w-3 h-3 animate-spin" />
            ) : (
              <Key className="w-3 h-3" />
            )}
            create key
          </button>
          <button
            onClick={onCancel}
            disabled={creating}
            className="px-4 py-2 text-[12px] text-[var(--color-text-dim)] hover:text-[var(--color-text)] rounded-[10px] transition-colors duration-150"
          >
            cancel
          </button>
        </div>
      </div>
    </div>
  );
}
