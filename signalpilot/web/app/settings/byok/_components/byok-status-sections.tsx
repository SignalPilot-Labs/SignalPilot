"use client";

import { AlertTriangle, Loader2, RefreshCw, Shield } from "lucide-react";
import { SectionHeader } from "~/components/ui/section-header";
import type { BYOKStatus } from "~/lib/api";

export function ByokMigrationStatus({
  status,
  reverting,
  onRevert,
}: {
  status: BYOKStatus | null;
  reverting: boolean;
  onRevert: () => void;
}) {
  return (
    <>
    {status && (
      <section className="mb-8">
        <SectionHeader icon={RefreshCw} title="migration status" />
        <div className="border border-[var(--color-border)] bg-[var(--color-bg-card)] rounded-[14px] overflow-hidden">
          <div className="p-6">
            <div className="grid grid-cols-3 gap-4 mb-4">
              <div className="p-3 border border-[var(--color-border)] rounded-[10px]">
                <p className="text-[10px] text-[var(--color-text-dim)] tracking-wider uppercase mb-1">total credentials</p>
                <p className="text-[20px] text-[var(--color-text)] font-mono tabular-nums">{status.total}</p>
              </div>
              <div className="p-3 border border-emerald-500/20 rounded-[10px]">
                <p className="text-[10px] text-emerald-400 tracking-wider uppercase mb-1">your key</p>
                <p className="text-[20px] text-emerald-400 font-mono tabular-nums">{status.byok}</p>
              </div>
              <div className="p-3 border border-[var(--color-border)] rounded-[10px]">
                <p className="text-[10px] text-[var(--color-text-dim)] tracking-wider uppercase mb-1">managed</p>
                <p className="text-[20px] text-[var(--color-text-muted)] font-mono tabular-nums">{status.managed}</p>
              </div>
            </div>

            {status.byok > 0 && (
              <div className="flex items-start gap-2 p-3 border border-amber-500/20 bg-amber-500/5 rounded-[10px] mb-4">
                <AlertTriangle className="w-3.5 h-3.5 text-amber-400 flex-shrink-0 mt-0.5" strokeWidth={1.5} />
                <div>
                  <p className="text-[11px] text-amber-400">
                    {status.byok} credential(s) encrypted with your key. revoking your key will make these credentials unreadable.
                  </p>
                </div>
              </div>
            )}

            {status.byok > 0 && (
              <button
                onClick={onRevert}
                disabled={reverting}
                className="flex items-center gap-2 px-3 py-2 text-[11px] border border-amber-500/30 rounded-[10px] text-amber-400 hover:bg-amber-500/10 transition-colors duration-150"
              >
                {reverting ? <Loader2 className="w-3 h-3 animate-spin" /> : <RefreshCw className="w-3 h-3" strokeWidth={1.5} />}
                revert all to managed encryption
              </button>
            )}
          </div>
        </div>
      </section>
    )}

    </>
  );
}

export function ByokHowItWorks() {
  return (
    <section className="mb-8">
      <SectionHeader icon={Shield} title="how bring-your-own-key works" />
      <div className="border border-[var(--color-border)] bg-[var(--color-bg-card)] rounded-[14px] overflow-hidden">
        <div className="p-6 space-y-3 text-[11px] text-[var(--color-text-dim)] leading-relaxed">
          <p><span className="text-[var(--color-text-muted)]">1.</span> you register a master key (KEK) — stored in your KMS, never leaves your infrastructure</p>
          <p><span className="text-[var(--color-text-muted)]">2.</span> SignalPilot generates a data encryption key (DEK) per credential, wraps it with your KEK</p>
          <p><span className="text-[var(--color-text-muted)]">3.</span> credentials are encrypted with the DEK — SignalPilot stores only the wrapped DEK + ciphertext</p>
          <p><span className="text-[var(--color-text-muted)]">4.</span> on query, SignalPilot unwraps the DEK via your KMS, decrypts the credential, connects</p>
          <p><span className="text-[var(--color-text-muted)]">5.</span> revoke your key at any time — all bring-your-own-key credentials become immediately unreadable</p>
        </div>
      </div>
    </section>  );
}
