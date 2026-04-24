"use client";

import { useEffect } from "react";
import { useClerk } from "@clerk/nextjs";
import { AuthShell } from "@/components/auth/auth-shell";
import { Loader2 } from "lucide-react";

export default function SSOCallbackPage() {
  const clerk = useClerk();

  useEffect(() => {
    if (!clerk.loaded) return;

    // Process the SSO callback — Clerk reads the URL params automatically
    clerk.handleRedirectCallback({
      afterSignInUrl: "/dashboard",
      afterSignUpUrl: "/onboarding",
    }).catch((err) => {
      console.error("[sso-callback] error:", err);
      // If callback processing fails, redirect to sign-in
      window.location.href = "/sign-in";
    });
  }, [clerk]);

  return (
    <AuthShell title="access terminal" subtitle="completing sign in...">
      <div className="flex flex-col items-center justify-center py-8 gap-3">
        <Loader2 className="w-5 h-5 animate-spin text-[var(--color-text-dim)]" />
        <p className="text-[12px] text-[var(--color-text-dim)] tracking-wider">
          verifying authentication...
        </p>
      </div>
    </AuthShell>
  );
}
