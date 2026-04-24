"use client";

import React, { useState } from "react";
import { Smartphone, Info } from "lucide-react";
import { PendingButton } from "@/components/ui/pending-button";
import { useUser, useReverification } from "@clerk/nextjs";
import type { PhoneNumberResource } from "@clerk/types";
import { SectionHeader } from "@/components/ui/section-header";
import { useToast } from "@/components/ui/toast";
import { ConfirmDialog } from "@/components/ui/confirm-dialog";
import {
  FIELD_INPUT_CLASS,
  LABEL_CLASS,
  ERROR_CLASS,
  NEUTRAL_CLASS,
} from "@/components/auth/auth-primitives";
import { isReverificationCancelledError } from "@/lib/security/use-reverify";
import { formatClerkError } from "@/lib/security/clerk-errors";

const SMS_DISABLED_CODES = new Set([
  "strategy_for_user_invalid",
  "feature_not_enabled",
  "form_param_unknown",
]);

function isSmsDisabledError(err: unknown): boolean {
  const e = err as { errors?: Array<{ code?: string }> };
  const code = e?.errors?.[0]?.code;
  return typeof code === "string" && SMS_DISABLED_CODES.has(code);
}

/**
 * Masks a phone number keeping the country code (+ prefix) and last 4 digits visible.
 * e.g. "+15551234567" → "+1 •••-•••-4567"
 * Falls back gracefully to bullet-masking for unknown formats.
 */
function maskPhone(phone: string): string {
  // Strip all non-digit characters to get the raw digits
  const digits = phone.replace(/\D/g, "");
  const last4 = digits.slice(-4);

  // Detect country-code prefix from the original string
  // We keep the leading + and first 1-3 digits as the country code portion
  const plusMatch = phone.match(/^\+(\d{1,3})/);
  if (plusMatch) {
    const cc = plusMatch[1];
    return `+${cc} •••-•••-${last4}`;
  }

  // No leading + — mask everything except last 4
  const masked = phone.slice(0, -4).replace(/[\d]/g, "•");
  return masked + last4;
}

export function SmsSection(): React.JSX.Element {
  const { user } = useUser();
  const { toast } = useToast();

  const [phoneInput, setPhoneInput] = useState("");
  const [otpCode, setOtpCode] = useState("");
  const [pendingPhone, setPendingPhone] = useState<PhoneNumberResource | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [neutralMsg, setNeutralMsg] = useState<string | null>(null);
  const [smsDisabled, setSmsDisabled] = useState(false);
  const [loading, setLoading] = useState(false);
  const [confirmRemoveOpen, setConfirmRemoveOpen] = useState(false);
  const [removeTargetId, setRemoveTargetId] = useState<string | null>(null);

  const reverifiedCreatePhone = useReverification(
    (phone: string) => user!.createPhoneNumber({ phoneNumber: phone }),
  );
  const reverifiedAttemptVerification = useReverification(
    (args: { phoneId: string; code: string }) =>
      user!.phoneNumbers.find((p) => p.id === args.phoneId)!.attemptVerification({ code: args.code }),
  );
  const reverifiedSetReserved = useReverification(
    (phoneId: string) =>
      user!.phoneNumbers.find((p) => p.id === phoneId)!.setReservedForSecondFactor({ reserved: true }),
  );
  const reverifiedMakeDefault = useReverification(
    (phoneId: string) =>
      user!.phoneNumbers.find((p) => p.id === phoneId)!.makeDefaultSecondFactor(),
  );
  const reverifiedDestroyPhone = useReverification(
    (phoneId: string) =>
      user!.phoneNumbers.find((p) => p.id === phoneId)!.destroy(),
  );

  const phones = user?.phoneNumbers ?? [];
  const verifiedPhone = phones.find(
    (p) => p.verification.status === "verified",
  );
  const reservedPhone = phones.find(
    (p) => p.verification.status === "verified" && p.reservedForSecondFactor,
  );

  async function handleAddPhone() {
    if (!phoneInput.trim()) { setError("enter a phone number"); return; }
    setError(null);
    setNeutralMsg(null);
    setSmsDisabled(false);
    setLoading(true);
    try {
      const phone = await reverifiedCreatePhone(phoneInput.trim());
      setPendingPhone(phone);
    } catch (err) {
      if (isReverificationCancelledError(err)) {
        setNeutralMsg("reverification required to add phone");
      } else if (isSmsDisabledError(err)) {
        setSmsDisabled(true);
      } else {
        setError(formatClerkError(err));
      }
    } finally {
      setLoading(false);
    }
  }

  async function handleVerifyPhone() {
    if (!pendingPhone || !otpCode.trim()) { setError("enter the verification code"); return; }
    setError(null);
    setNeutralMsg(null);
    setLoading(true);
    try {
      const verified = await reverifiedAttemptVerification({ phoneId: pendingPhone.id, code: otpCode.trim() });
      // Promote to second factor immediately after verification
      await reverifiedSetReserved(verified.id);
      await reverifiedMakeDefault(verified.id);
      await user?.reload();
      setPendingPhone(null);
      setPhoneInput("");
      setOtpCode("");
      toast("phone number added as second factor", "success");
    } catch (err) {
      if (isReverificationCancelledError(err)) {
        setNeutralMsg("reverification required");
      } else {
        setError(formatClerkError(err));
      }
    } finally {
      setLoading(false);
    }
  }

  async function handlePromote(phoneId: string) {
    setError(null);
    setNeutralMsg(null);
    setLoading(true);
    try {
      await reverifiedSetReserved(phoneId);
      await reverifiedMakeDefault(phoneId);
      await user?.reload();
      toast("phone promoted to second factor", "success");
    } catch (err) {
      if (isReverificationCancelledError(err)) {
        setNeutralMsg("reverification required to promote phone");
      } else {
        setError(formatClerkError(err));
      }
    } finally {
      setLoading(false);
    }
  }

  function requestRemove(phoneId: string) {
    setRemoveTargetId(phoneId);
    setConfirmRemoveOpen(true);
  }

  async function handleRemoveConfirmed() {
    const phoneId = removeTargetId;
    setConfirmRemoveOpen(false);
    setRemoveTargetId(null);
    if (!phoneId) return;
    setError(null);
    setNeutralMsg(null);
    setLoading(true);
    try {
      await reverifiedDestroyPhone(phoneId);
      await user?.reload();
      toast("phone number removed", "success");
    } catch (err) {
      if (isReverificationCancelledError(err)) {
        setNeutralMsg("reverification required to remove phone");
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
        <SectionHeader icon={Smartphone} title="sms 2fa" />
        <div className="border border-[var(--color-border)] bg-[var(--color-bg-card)] overflow-hidden">
          <div className="p-6 space-y-4">
            {smsDisabled && (
              <div className="flex items-start gap-2 p-3 border border-[var(--color-border)]">
                <Info className="w-3.5 h-3.5 text-[var(--color-text-dim)] mt-0.5 flex-shrink-0" strokeWidth={1.5} />
                <p className="text-[11px] text-[var(--color-text-dim)] tracking-wider">
                  sms 2fa is disabled for this instance. enable it in the clerk dashboard under multi-factor authentication.
                </p>
              </div>
            )}

            {reservedPhone ? (
              <>
                <p className="text-[12px] text-[var(--color-text-dim)] tracking-wider">
                  sms 2fa is <span className="text-[var(--color-success)]">on</span> — {maskPhone(reservedPhone.phoneNumber)}
                </p>
                <div role="alert" aria-live="assertive" aria-atomic="true">
                  {error && <p className={ERROR_CLASS}>{error}</p>}
                </div>
                <div role="status" aria-live="polite" aria-atomic="true">
                  {neutralMsg && <p className={NEUTRAL_CLASS}>{neutralMsg}</p>}
                </div>
                <PendingButton
                  variant="danger"
                  size="sm"
                  onClick={() => requestRemove(reservedPhone.id)}
                  pending={loading}
                  pendingLabel="removing…"
                >
                  remove phone number
                </PendingButton>
              </>
            ) : verifiedPhone && !reservedPhone ? (
              <>
                <p className="text-[12px] text-[var(--color-text-dim)] tracking-wider">
                  verified phone: {maskPhone(verifiedPhone.phoneNumber)} — not set as second factor
                </p>
                <div role="alert" aria-live="assertive" aria-atomic="true">
                  {error && <p className={ERROR_CLASS}>{error}</p>}
                </div>
                <div role="status" aria-live="polite" aria-atomic="true">
                  {neutralMsg && <p className={NEUTRAL_CLASS}>{neutralMsg}</p>}
                </div>
                <PendingButton
                  onClick={() => handlePromote(verifiedPhone.id)}
                  pending={loading}
                  pendingLabel="promoting…"
                >
                  promote to 2fa
                </PendingButton>
              </>
            ) : pendingPhone ? (
              <>
                <p className="text-[12px] text-[var(--color-text-dim)] tracking-wider">
                  a verification code was sent to {phoneInput}
                </p>
                <div className="flex flex-col gap-1">
                  <label htmlFor="sms-otp-code" className={LABEL_CLASS}>verification code</label>
                  <input
                    id="sms-otp-code"
                    type="text"
                    inputMode="numeric"
                    maxLength={6}
                    value={otpCode}
                    onChange={(e) => setOtpCode(e.target.value.replace(/\D/g, ""))}
                    placeholder="000000"
                    className={FIELD_INPUT_CLASS}
                  />
                </div>
                <div role="alert" aria-live="assertive" aria-atomic="true">
                  {error && <p className={ERROR_CLASS}>{error}</p>}
                </div>
                <div role="status" aria-live="polite" aria-atomic="true">
                  {neutralMsg && <p className={NEUTRAL_CLASS}>{neutralMsg}</p>}
                </div>
                <PendingButton
                  onClick={handleVerifyPhone}
                  pending={loading}
                  pendingLabel="verifying…"
                  disabled={loading || otpCode.length < 4}
                >
                  verify phone
                </PendingButton>
                <button
                  onClick={() => { setPendingPhone(null); setPhoneInput(""); setOtpCode(""); setError(null); }}
                  className="text-[11px] text-[var(--color-text-dim)] hover:text-[var(--color-text)] tracking-wider underline underline-offset-2 transition-colors font-mono focus:outline-none focus-visible:outline-none focus-visible:ring-1 focus-visible:ring-[var(--color-text)]"
                >
                  cancel
                </button>
              </>
            ) : (
              <>
                <p className="text-[12px] text-[var(--color-text-dim)] tracking-wider">
                  no phone number configured as second factor
                </p>
                <div className="flex flex-col gap-1">
                  <label htmlFor="sms-phone-input" className={LABEL_CLASS}>phone number</label>
                  <input
                    id="sms-phone-input"
                    type="tel"
                    value={phoneInput}
                    onChange={(e) => setPhoneInput(e.target.value)}
                    placeholder="+1 555 000 0000"
                    className={FIELD_INPUT_CLASS}
                  />
                </div>
                <div role="alert" aria-live="assertive" aria-atomic="true">
                  {error && <p className={ERROR_CLASS}>{error}</p>}
                </div>
                <div role="status" aria-live="polite" aria-atomic="true">
                  {neutralMsg && <p className={NEUTRAL_CLASS}>{neutralMsg}</p>}
                </div>
                <PendingButton
                  onClick={handleAddPhone}
                  pending={loading}
                  pendingLabel="adding…"
                >
                  add phone number
                </PendingButton>
              </>
            )}
          </div>
        </div>
      </section>

      <ConfirmDialog
        open={confirmRemoveOpen}
        title="remove phone number"
        message="remove this phone number? it will no longer be used as a second factor for sign-in."
        confirmLabel="remove"
        variant="danger"
        onConfirm={handleRemoveConfirmed}
        onCancel={() => { setConfirmRemoveOpen(false); setRemoveTargetId(null); }}
      />
    </>
  );
}
