"use client";

/**
 * Sign-in page — AuthShell wrapper with dynamically-imported Elements flow.
 *
 * @clerk/elements uses browser-only `location` API at module scope.
 * SignInFlow is imported with { ssr: false } to prevent SSR errors during build.
 * No fallbackRedirectUrl here — set via ClerkProvider in layout.tsx.
 */

import dynamic from "next/dynamic";
import { Loader2 } from "lucide-react";
import { AuthShell } from "@/components/auth/auth-shell";

const SignInFlow = dynamic(
  () =>
    import("@/components/auth/sign-in-flow").then((m) => ({
      default: m.SignInFlow,
    })),
  {
    ssr: false,
    loading: () => (
      <div className="flex items-center justify-center py-8">
        <Loader2 className="w-4 h-4 animate-spin text-[var(--color-text-dim)]" />
      </div>
    ),
  }
);

export default function SignInPage() {
  return (
    <AuthShell title="access terminal" subtitle="sign in to signalpilot">
      <SignInFlow />
    </AuthShell>
  );
}
