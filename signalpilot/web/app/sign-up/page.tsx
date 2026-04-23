"use client";

/**
 * Sign-up page — AuthShell wrapper with dynamically-imported Elements flow.
 *
 * @clerk/elements uses browser-only `location` API at module scope.
 * SignUpFlow is imported with { ssr: false } to prevent SSR errors during build.
 * No fallbackRedirectUrl here — set via ClerkProvider in layout.tsx.
 */

import dynamic from "next/dynamic";
import { Loader2 } from "lucide-react";
import { AuthShell } from "@/components/auth/auth-shell";

const SignUpFlow = dynamic(
  () =>
    import("@/components/auth/sign-up-flow").then((m) => ({
      default: m.SignUpFlow,
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

export default function SignUpPage() {
  return (
    <AuthShell title="boot sequence" subtitle="create your signalpilot account">
      <SignUpFlow />
    </AuthShell>
  );
}
