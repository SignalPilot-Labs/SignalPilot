"use client";

import { KeyRound, Loader2, Trash2, X } from "lucide-react";
import { StatusDot } from "~/components/ui/data-viz";
import { SectionHeader } from "~/components/ui/section-header";
import { formatUpdatedAt } from "../_lib/helpers";
import type { OrgSecretsState } from "./use-org-secrets";

export function AnthropicKeySection({
  orgSecrets,
  orgSecretsLoading,
  orgSecretsLoadError,
  orgSecretsReadOnly,
  anthropicKey,
  setAnthropicKey,
  savingAnthropicKey,
  confirmRemoveAnthropicKey,
  setConfirmRemoveAnthropicKey,
  fetchOrgSecrets,
  handleSaveAnthropicKey,
  handleRemoveAnthropicKey,
}: OrgSecretsState) {
  return (
    <section className="mb-8">
      <div className="flex items-center justify-between mb-4">
        <SectionHeader icon={KeyRound} title="anthropic api key" />
      </div>

      <div className="border border-[var(--color-border)] bg-[var(--color-bg-card)] p-5">
        {orgSecretsLoading ? (
          <div className="flex items-center gap-2 text-[12px] text-[var(--color-text-dim)] tracking-wider">
            <Loader2 className="w-3 h-3 animate-spin" />
            checking key
          </div>
        ) : orgSecretsLoadError ? (
          <div className="flex flex-col gap-3 sm:flex-row sm:items-center sm:justify-between">
            <div className="flex items-center gap-2">
              <StatusDot status="error" size={4} />
              <span className="text-[12px] text-[var(--color-text-dim)] tracking-wider">
                failed to load
              </span>
            </div>
            <button
              onClick={fetchOrgSecrets}
              className="px-4 py-2 text-[12px] text-[var(--color-text-dim)] border border-[var(--color-border)] hover:border-[var(--color-border-hover)] hover:text-[var(--color-text)] transition-all tracking-wider uppercase"
            >
              retry
            </button>
          </div>
        ) : (
          <div className="space-y-4">
            <div className="flex flex-col gap-3 sm:flex-row sm:items-start sm:justify-between">
              <div className="space-y-1">
                <div className="flex items-center gap-2">
                  <StatusDot status={orgSecrets?.has_key ? "healthy" : "warning"} size={4} />
                  <span className="text-[13px] text-[var(--color-text)] tracking-wider font-medium">
                    {orgSecrets?.has_key ? "key set" : "no key"}
                  </span>
                </div>
                <div className="space-y-1 text-[11px] text-[var(--color-text-dim)] tracking-wider">
                  {orgSecrets?.key_preview && (
                    <p>
                      preview: <span className="text-[var(--color-text-muted)] font-mono">{orgSecrets.key_preview}</span>
                    </p>
                  )}
                  <p>
                    updated: <span className="text-[var(--color-text-muted)]">{formatUpdatedAt(orgSecrets?.updated_at ?? null)}</span>
                  </p>
                  {orgSecretsReadOnly && (
                    <p className="text-[var(--color-warning)]">
                      read-only: write permission required
                    </p>
                  )}
                </div>
              </div>
              {orgSecrets?.has_key && (
                <div className="flex items-center gap-1.5">
                  {confirmRemoveAnthropicKey ? (
                    <>
                      <button
                        onClick={handleRemoveAnthropicKey}
                        disabled={savingAnthropicKey || orgSecretsReadOnly}
                        className="flex items-center gap-1.5 px-3 py-1.5 text-[12px] text-[var(--color-error)] border border-[var(--color-error)]/30 hover:border-[var(--color-error)] transition-all tracking-wider uppercase disabled:opacity-30"
                      >
                        {savingAnthropicKey ? <Loader2 className="w-3 h-3 animate-spin" /> : null}
                        confirm
                      </button>
                      <button
                        onClick={() => setConfirmRemoveAnthropicKey(false)}
                        className="p-1.5 text-[var(--color-text-dim)] hover:text-[var(--color-text)] transition-colors"
                      >
                        <X className="w-3 h-3" />
                      </button>
                    </>
                  ) : (
                    <button
                      onClick={() => setConfirmRemoveAnthropicKey(true)}
                      disabled={orgSecretsReadOnly}
                      className="flex items-center gap-1.5 px-3 py-1.5 text-[12px] text-[var(--color-text-dim)] border border-[var(--color-border)] hover:border-[var(--color-error)]/50 hover:text-[var(--color-error)] transition-all tracking-wider uppercase disabled:opacity-30"
                    >
                      <Trash2 className="w-3 h-3" />
                      remove
                    </button>
                  )}
                </div>
              )}
            </div>

            <div className="border-t border-[var(--color-border)] pt-4">
              <label htmlFor="anthropic-api-key" className="sr-only">Anthropic API key</label>
              <p className="mb-3 text-[12px] leading-5 text-[var(--color-text-dim)] tracking-wider">
                Set your{" "}
                <a
                  href="https://platform.claude.com"
                  target="_blank"
                  rel="noopener noreferrer"
                  className="text-[var(--color-text)] underline decoration-[var(--color-border-hover)] underline-offset-4 hover:decoration-[var(--color-text)]"
                >
                  Anthropic API key
                </a>{" "}
                to enable SignalPilot Agents
              </p>
              <div className="flex flex-col gap-2 sm:flex-row">
                <input
                  id="anthropic-api-key"
                  type="password"
                  value={anthropicKey}
                  onChange={(event) => setAnthropicKey(event.target.value)}
                  onKeyDown={(event) => { if (event.key === "Enter") void handleSaveAnthropicKey(); }}
                  disabled={savingAnthropicKey || orgSecretsReadOnly}
                  placeholder="sk-ant-..."
                  className="min-w-0 flex-1 px-3 py-2 bg-[var(--color-bg-input)] border border-[var(--color-border)] text-xs font-mono focus:outline-none disabled:opacity-40"
                />
                <button
                  onClick={handleSaveAnthropicKey}
                  disabled={!anthropicKey.trim() || savingAnthropicKey || orgSecretsReadOnly}
                  className="flex items-center justify-center gap-2 px-4 py-2 bg-[var(--color-text)] text-[var(--color-bg)] text-[12px] tracking-wider uppercase transition-all hover:opacity-90 disabled:opacity-30"
                >
                  {savingAnthropicKey ? <Loader2 className="w-3 h-3 animate-spin" /> : <KeyRound className="w-3 h-3" />}
                  {orgSecrets?.has_key ? "rotate" : "save"}
                </button>
              </div>
            </div>
          </div>
        )}
      </div>
    </section>
  );
}
