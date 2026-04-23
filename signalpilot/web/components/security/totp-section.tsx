"use client";

import React, { useState } from "react";
import { ShieldCheck, Loader2 } from "lucide-react";
import { useUser, useReverification } from "@clerk/nextjs";
import type { TOTPResource } from "@clerk/types";
import { SectionHeader } from "@/components/ui/section-header";
import { useToast } from "@/components/ui/toast";
import { ConfirmDialog } from "@/components/ui/confirm-dialog";
import { QrCode } from "./qr-code";
import { RevealOnce } from "./reveal-once";
import {
  FIELD_INPUT_CLASS,
  PRIMARY_BTN_CLASS,
  SECONDARY_BTN_CLASS,
  LABEL_CLASS,
  ERROR_CLASS,
  NEUTRAL_CLASS,
} from "@/components/auth/auth-primitives";
import { CopyButton } from "@/components/ui/copy-button";
import { isReverificationCancelledError } from "@/lib/security/use-reverify";
import { formatClerkError } from "@/lib/security/clerk-errors";

export function TotpSection(): React.JSX.Element {
  const { user } = useUser();
  const { toast } = useToast();

  const [totpResource, setTotpResource] = useState<TOTPResource | null>(null);
  const [otpCode, setOtpCode] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [neutralMsg, setNeutralMsg] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);
  const [backupCodeError, setBackupCodeError] = useState<string | null>(null);
  const [firstTimeBackupCodes, setFirstTimeBackupCodes] = useState<string[] | null>(null);
  const [confirmDisableOpen, setConfirmDisableOpen] = useState(false);

  const reverifiedCreateTOTP = useReverification(() => user!.createTOTP());
  const reverifiedVerifyTOTP = useReverification(
    (args: { code: string }) => user!.verifyTOTP(args),
  );
  const reverifiedCreateBackupCode = useReverification(() => user!.createBackupCode());
  const reverifiedDisableTOTP = useReverification(() => user!.disableTOTP());

  const totpEnabled = user?.totpEnabled ?? false;

  async function handleStartEnroll() {
    if (!user) return;
    setError(null);
    setNeutralMsg(null);
    setLoading(true);
    try {
      const totp = await reverifiedCreateTOTP();
      setTotpResource(totp);
    } catch (err) {
      if (isReverificationCancelledError(err)) {
        setNeutralMsg("reverification required to enable authenticator app");
      } else {
        setError(formatClerkError(err));
      }
    } finally {
      setLoading(false);
    }
  }

  async function handleVerify() {
    if (!user || !otpCode) { setError("enter the code from your authenticator app"); return; }
    setError(null);
    setNeutralMsg(null);
    setBackupCodeError(null);
    setLoading(true);
    try {
      await reverifiedVerifyTOTP({ code: otpCode });
      // Immediately generate backup codes BEFORE calling user.reload()
      try {
        const result = await reverifiedCreateBackupCode();
        setFirstTimeBackupCodes(result.codes);
        setTotpResource(null);
        setOtpCode("");
        toast("authenticator app enabled", "success");
      } catch (backupErr) {
        // TOTP is verified but backup codes failed — surface error, don't reload
        setTotpResource(null);
        setOtpCode("");
        if (isReverificationCancelledError(backupErr)) {
          setBackupCodeError("reverification required to generate backup codes");
        } else {
          setBackupCodeError(formatClerkError(backupErr));
        }
      }
    } catch (err) {
      if (isReverificationCancelledError(err)) {
        setNeutralMsg("reverification required to verify code");
      } else {
        setError(formatClerkError(err));
      }
    } finally {
      setLoading(false);
    }
  }

  async function handleRetryBackupCodes() {
    setBackupCodeError(null);
    setLoading(true);
    try {
      const result = await reverifiedCreateBackupCode();
      setFirstTimeBackupCodes(result.codes);
    } catch (err) {
      if (isReverificationCancelledError(err)) {
        setBackupCodeError("reverification required to generate backup codes");
      } else {
        setBackupCodeError(formatClerkError(err));
      }
    } finally {
      setLoading(false);
    }
  }

  async function handleDismissBackupCodes() {
    setFirstTimeBackupCodes(null);
    await user?.reload();
  }

  async function handleDisableConfirmed() {
    setConfirmDisableOpen(false);
    if (!user) return;
    setError(null);
    setNeutralMsg(null);
    setLoading(true);
    try {
      await reverifiedDisableTOTP();
      await user.reload();
      toast("authenticator app disabled", "success");
    } catch (err) {
      if (isReverificationCancelledError(err)) {
        setNeutralMsg("reverification required to disable authenticator app");
      } else {
        setError(formatClerkError(err));
      }
    } finally {
      setLoading(false);
    }
  }

  // Show first-time backup codes (after TOTP verify, before user.reload)
  if (firstTimeBackupCodes) {
    return (
      <section className="mb-8">
        <SectionHeader icon={ShieldCheck} title="authenticator app" />
        <RevealOnce
          title="backup codes"
          description="save these backup codes somewhere safe. you will not be able to see them again. each code can only be used once."
          lines={firstTimeBackupCodes}
          onDismiss={handleDismissBackupCodes}
        />
      </section>
    );
  }

  // TOTP verified but backup codes failed — keep success visible + inline retry
  if (backupCodeError) {
    return (
      <section className="mb-8">
        <SectionHeader icon={ShieldCheck} title="authenticator app" />
        <div className="border border-[var(--color-border)] bg-[var(--color-bg-card)] p-5 space-y-3">
          <p className="text-[12px] text-[var(--color-success)] tracking-wider">authenticator app enabled</p>
          <div role="alert" aria-live="assertive" aria-atomic="true">
            <p className={ERROR_CLASS}>{backupCodeError}</p>
          </div>
          <button
            onClick={handleRetryBackupCodes}
            disabled={loading}
            className={PRIMARY_BTN_CLASS}
          >
            {loading && <Loader2 className="w-3.5 h-3.5 animate-spin inline mr-2" />}
            retry generate backup codes
          </button>
        </div>
      </section>
    );
  }

  return (
    <>
      <section className="mb-8">
        <SectionHeader icon={ShieldCheck} title="authenticator app" />
        <div className="border border-[var(--color-border)] bg-[var(--color-bg-card)] overflow-hidden">
          <div className="p-6 space-y-4">
            {totpEnabled && !totpResource ? (
              <>
                <p className="text-[12px] text-[var(--color-text-dim)] tracking-wider">
                  mfa is <span className="text-[var(--color-success)]">on</span> — authenticator app enabled
                </p>
                {/* aria-live regions for async status announcements */}
                <div role="alert" aria-live="assertive" aria-atomic="true">
                  {error && <p className={ERROR_CLASS}>{error}</p>}
                </div>
                <div role="status" aria-live="polite" aria-atomic="true">
                  {neutralMsg && <p className={NEUTRAL_CLASS}>{neutralMsg}</p>}
                </div>
                <button
                  onClick={() => setConfirmDisableOpen(true)}
                  disabled={loading}
                  className={SECONDARY_BTN_CLASS}
                >
                  {loading && <Loader2 className="w-3 h-3 animate-spin inline mr-1.5" />}
                  disable authenticator app
                </button>
              </>
            ) : totpResource ? (
              <>
                <p className="text-[12px] text-[var(--color-text-dim)] tracking-wider mb-2">
                  scan this qr code with your authenticator app
                </p>
                <QrCode uri={totpResource.uri!} size={192} />
                <div className="flex flex-col gap-1 mt-2">
                  <span className={LABEL_CLASS}>or enter secret manually</span>
                  <div className="flex items-center gap-2">
                    <kbd className="px-3 py-1.5 border border-[var(--color-border)] bg-[var(--color-bg)] font-mono text-[12px] text-[var(--color-text)] tracking-widest">
                      {totpResource.secret}
                    </kbd>
                    <CopyButton text={totpResource.secret ?? ""} />
                  </div>
                </div>
                <div className="flex flex-col gap-1 pt-2">
                  <label htmlFor="totp-otp-code" className={LABEL_CLASS}>verification code</label>
                  <input
                    id="totp-otp-code"
                    type="text"
                    inputMode="numeric"
                    maxLength={6}
                    value={otpCode}
                    onChange={(e) => setOtpCode(e.target.value.replace(/\D/g, ""))}
                    placeholder="000000"
                    className={FIELD_INPUT_CLASS}
                    aria-describedby={error ? "totp-error" : neutralMsg ? "totp-neutral" : undefined}
                  />
                </div>
                <div role="alert" aria-live="assertive" aria-atomic="true">
                  {error && <p id="totp-error" className={ERROR_CLASS}>{error}</p>}
                </div>
                <div role="status" aria-live="polite" aria-atomic="true">
                  {neutralMsg && <p id="totp-neutral" className={NEUTRAL_CLASS}>{neutralMsg}</p>}
                </div>
                <div className="flex items-center gap-3 pt-1">
                  <button
                    onClick={handleVerify}
                    disabled={loading || otpCode.length !== 6}
                    className={PRIMARY_BTN_CLASS}
                  >
                    {loading && <Loader2 className="w-3.5 h-3.5 animate-spin inline mr-2" />}
                    verify and enable
                  </button>
                  <button
                    onClick={() => { setTotpResource(null); setOtpCode(""); setError(null); }}
                    className={SECONDARY_BTN_CLASS}
                  >
                    cancel
                  </button>
                </div>
              </>
            ) : (
              <>
                <p className="text-[12px] text-[var(--color-text-dim)] tracking-wider">
                  no authenticator app configured
                </p>
                <div role="alert" aria-live="assertive" aria-atomic="true">
                  {error && <p className={ERROR_CLASS}>{error}</p>}
                </div>
                <div role="status" aria-live="polite" aria-atomic="true">
                  {neutralMsg && <p className={NEUTRAL_CLASS}>{neutralMsg}</p>}
                </div>
                <button
                  onClick={handleStartEnroll}
                  disabled={loading}
                  className={PRIMARY_BTN_CLASS}
                >
                  {loading && <Loader2 className="w-3.5 h-3.5 animate-spin inline mr-2" />}
                  enable authenticator app
                </button>
              </>
            )}
          </div>
        </div>
      </section>

      <ConfirmDialog
        open={confirmDisableOpen}
        title="disable authenticator app"
        message="disable authenticator app? you will lose 2fa protection on this account. this cannot be undone without re-enrolling."
        confirmLabel="disable"
        variant="danger"
        onConfirm={handleDisableConfirmed}
        onCancel={() => setConfirmDisableOpen(false)}
      />
    </>
  );
}
