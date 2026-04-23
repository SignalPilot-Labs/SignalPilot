"use client";

import React, { useState } from "react";
import { Lock, CheckCircle2, Loader2 } from "lucide-react";
import { useUser, useReverification } from "@clerk/nextjs";
import { SectionHeader } from "@/components/ui/section-header";
import { useToast } from "@/components/ui/toast";
import { FIELD_INPUT_CLASS, PRIMARY_BTN_CLASS, LABEL_CLASS, ERROR_CLASS, NEUTRAL_CLASS } from "@/components/auth/auth-primitives";
import { isReverificationCancelledError } from "@/lib/security/use-reverify";
import { formatClerkError } from "@/lib/security/clerk-errors";

export function PasswordSection(): React.JSX.Element {
  const { user } = useUser();
  const { toast } = useToast();
  const [currentPassword, setCurrentPassword] = useState("");
  const [newPassword, setNewPassword] = useState("");
  const [confirmPassword, setConfirmPassword] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [neutralMsg, setNeutralMsg] = useState<string | null>(null);
  const [saving, setSaving] = useState(false);
  const [justChanged, setJustChanged] = useState(false);

  const reverifiedUpdatePassword = useReverification(
    (args: Parameters<NonNullable<typeof user>["updatePassword"]>[0]) =>
      user!.updatePassword(args),
  );

  async function handleSubmit(e: React.FormEvent) {
    e.preventDefault();
    if (!user) return;
    setError(null);
    setNeutralMsg(null);

    if (!currentPassword) { setError("current password is required"); return; }
    if (!newPassword) { setError("new password is required"); return; }
    if (newPassword !== confirmPassword) { setError("passwords do not match"); return; }

    setSaving(true);
    try {
      await reverifiedUpdatePassword({
        currentPassword,
        newPassword,
        signOutOfOtherSessions: true,
      });
      setCurrentPassword("");
      setNewPassword("");
      setConfirmPassword("");
      setJustChanged(true);
      setTimeout(() => setJustChanged(false), 4000);
      toast("password updated", "success");
    } catch (err) {
      if (isReverificationCancelledError(err)) {
        setNeutralMsg("reverification required to change password");
      } else {
        setError(formatClerkError(err));
      }
    } finally {
      setSaving(false);
    }
  }

  return (
    <section className="mb-8">
      <SectionHeader icon={Lock} title="password" />
      <div className="border border-[var(--color-border)] bg-[var(--color-bg-card)] overflow-hidden">
        <form onSubmit={handleSubmit} className="p-6 space-y-4">
          <div className="flex flex-col gap-1">
            <label htmlFor="current-password" className={LABEL_CLASS}>current password</label>
            <input
              id="current-password"
              type="password"
              value={currentPassword}
              onChange={(e) => setCurrentPassword(e.target.value)}
              autoComplete="current-password"
              className={FIELD_INPUT_CLASS}
            />
          </div>
          <div className="flex flex-col gap-1">
            <label htmlFor="new-password" className={LABEL_CLASS}>new password</label>
            <input
              id="new-password"
              type="password"
              value={newPassword}
              onChange={(e) => setNewPassword(e.target.value)}
              autoComplete="new-password"
              className={FIELD_INPUT_CLASS}
            />
          </div>
          <div className="flex flex-col gap-1">
            <label htmlFor="confirm-password" className={LABEL_CLASS}>confirm new password</label>
            <input
              id="confirm-password"
              type="password"
              value={confirmPassword}
              onChange={(e) => setConfirmPassword(e.target.value)}
              autoComplete="new-password"
              className={FIELD_INPUT_CLASS}
            />
            {confirmPassword.length > 0 && newPassword !== confirmPassword && (
              <p className={NEUTRAL_CLASS}>passwords don&apos;t match yet</p>
            )}
          </div>

          {/* aria-live regions so screen readers announce async state changes */}
          <div role="alert" aria-live="assertive" aria-atomic="true">
            {error && <p className={ERROR_CLASS}>{error}</p>}
          </div>
          <div role="status" aria-live="polite" aria-atomic="true">
            {neutralMsg && <p className={NEUTRAL_CLASS}>{neutralMsg}</p>}
            {justChanged && (
              <span className="flex items-center gap-1 text-[12px] text-[var(--color-success)] tracking-wider animate-fade-in">
                <CheckCircle2 className="w-3 h-3" /> password updated
              </span>
            )}
          </div>

          <button type="submit" disabled={saving} className={PRIMARY_BTN_CLASS}>
            {saving ? <Loader2 className="w-3.5 h-3.5 animate-spin inline mr-2" /> : null}
            change password
          </button>
        </form>
      </div>
    </section>
  );
}
