"use client";

import { Loader2 } from "lucide-react";
import { useUser } from "@clerk/nextjs";
import { PageHeader, TerminalBar } from "@/components/ui/page-header";
import { StatusDot } from "@/components/ui/data-viz";
import { PasswordSection } from "@/components/security/password-section";
import { TotpSection } from "@/components/security/totp-section";
import { SmsSection } from "@/components/security/sms-section";
import { BackupCodesSection } from "@/components/security/backup-codes-section";

export default function AccountSecurityClient() {
  const { user, isLoaded } = useUser();

  if (!isLoaded) {
    return (
      <div className="flex items-center justify-center h-96">
        <Loader2 className="w-5 h-5 animate-spin text-[var(--color-text-dim)]" />
      </div>
    );
  }

  if (!user) return null;

  const mfaStatus = user.twoFactorEnabled ? "healthy" : "unknown";

  return (
    <div className="p-8 max-w-3xl animate-fade-in">
      <PageHeader
        title="account security"
        subtitle="security"
        description="manage your password, multi-factor authentication, and backup codes"
      />

      <TerminalBar
        path="security --audit"
        status={<StatusDot status={mfaStatus} size={4} />}
      >
        <div className="flex items-center gap-6 text-xs">
          <span className="text-[var(--color-text-dim)]">
            mfa:{" "}
            <code className={`text-[12px] ${user.twoFactorEnabled ? "text-[var(--color-success)]" : "text-[var(--color-text-muted)]"}`}>
              {user.twoFactorEnabled ? "on" : "off"}
            </code>
          </span>
          <span className="text-[var(--color-text-dim)]">
            totp:{" "}
            <code className={`text-[12px] ${user.totpEnabled ? "text-[var(--color-success)]" : "text-[var(--color-text-muted)]"}`}>
              {user.totpEnabled ? "on" : "off"}
            </code>
          </span>
        </div>
      </TerminalBar>

      <PasswordSection />
      <TotpSection />
      <SmsSection />
      <BackupCodesSection />
    </div>
  );
}
