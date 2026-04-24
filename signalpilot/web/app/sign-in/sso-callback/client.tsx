"use client";

import { AuthenticateWithRedirectCallback } from "@clerk/nextjs";
import { AuthShell } from "@/components/auth/auth-shell";
import { Loader2 } from "lucide-react";

export default function SSOCallbackClient() {
  return (
    <AuthShell title="access terminal" subtitle="completing sign in...">
      <div className="flex flex-col items-center justify-center py-8 gap-3">
        <Loader2 className="w-5 h-5 animate-spin text-[var(--color-text-dim)]" />
        <p className="text-[12px] text-[var(--color-text-dim)] tracking-wider">
          verifying authentication...
        </p>
      </div>
      <AuthenticateWithRedirectCallback
        afterSignInUrl="/dashboard"
        afterSignUpUrl="/onboarding"
      />
    </AuthShell>
  );
}
