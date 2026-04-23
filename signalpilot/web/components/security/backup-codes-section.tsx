"use client";

import React, { useState } from "react";
import { KeyRound, Loader2 } from "lucide-react";
import { useUser, useReverification } from "@clerk/nextjs";
import { SectionHeader } from "@/components/ui/section-header";
import { useToast } from "@/components/ui/toast";
import { ConfirmDialog } from "@/components/ui/confirm-dialog";
import { RevealOnce } from "./reveal-once";
import { SECONDARY_BTN_CLASS, ERROR_CLASS, NEUTRAL_CLASS } from "@/components/auth/auth-primitives";
import { isReverificationCancelledError } from "@/lib/security/use-reverify";
import { formatClerkError } from "@/lib/security/clerk-errors";

export function BackupCodesSection(): React.JSX.Element {
  const { user } = useUser();
  const { toast } = useToast();

  const [codes, setCodes] = useState<string[] | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [neutralMsg, setNeutralMsg] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);
  const [confirmRegenOpen, setConfirmRegenOpen] = useState(false);

  const reverifiedCreateBackupCode = useReverification(() => user!.createBackupCode());

  // Only visible when at least one second factor is enabled
  if (!user?.twoFactorEnabled) return <></>;

  async function handleRegenerateConfirmed() {
    setConfirmRegenOpen(false);
    setError(null);
    setNeutralMsg(null);
    setLoading(true);
    try {
      const result = await reverifiedCreateBackupCode();
      setCodes(result.codes);
      toast("backup codes regenerated", "success");
    } catch (err) {
      if (isReverificationCancelledError(err)) {
        setNeutralMsg("reverification required to regenerate backup codes");
      } else {
        setError(formatClerkError(err));
      }
    } finally {
      setLoading(false);
    }
  }

  return (
    <>
      <section className="mb-8">
        <SectionHeader icon={KeyRound} title="backup codes" />

        {codes ? (
          <RevealOnce
            title="backup codes"
            description="save these backup codes somewhere safe. they are shown only once. each code can only be used once. regenerating invalidates all previous codes."
            lines={codes}
            onDismiss={() => setCodes(null)}
          />
        ) : (
          <div className="border border-[var(--color-border)] bg-[var(--color-bg-card)] overflow-hidden">
            <div className="p-6 space-y-3">
              <p className="text-[12px] text-[var(--color-text-dim)] tracking-wider">
                backup codes let you sign in if you lose access to your authenticator app or phone.
                regenerating will invalidate any previously generated codes.
              </p>
              <div role="alert" aria-live="assertive" aria-atomic="true">
                {error && <p className={ERROR_CLASS}>{error}</p>}
              </div>
              <div role="status" aria-live="polite" aria-atomic="true">
                {neutralMsg && <p className={NEUTRAL_CLASS}>{neutralMsg}</p>}
              </div>
              <button
                onClick={() => setConfirmRegenOpen(true)}
                disabled={loading}
                className={SECONDARY_BTN_CLASS}
              >
                {loading && <Loader2 className="w-3 h-3 animate-spin inline mr-1.5" />}
                regenerate backup codes
              </button>
            </div>
          </div>
        )}
      </section>

      <ConfirmDialog
        open={confirmRegenOpen}
        title="regenerate backup codes"
        message="regenerating backup codes will permanently invalidate all previously generated codes. any printed or saved codes will no longer work. continue?"
        confirmLabel="regenerate"
        variant="danger"
        onConfirm={handleRegenerateConfirmed}
        onCancel={() => setConfirmRegenOpen(false)}
      />
    </>
  );
}
