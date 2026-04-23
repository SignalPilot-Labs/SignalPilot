"use client";

/**
 * Onboarding page — entry point.
 *
 * - Local mode: immediate redirect to /dashboard (no onboarding needed).
 * - Cloud mode: renders CloudOnboardingContent which handles the team-creation
 *   step + API key wizard. All @clerk/nextjs hooks live in onboarding-cloud.tsx
 *   to prevent them from being pulled into the SSR bundle in local-mode builds.
 */

import dynamic from "next/dynamic";
import { useRouter } from "next/navigation";
import { useEffect } from "react";
import { Loader2 } from "lucide-react";
import { useAppAuth } from "@/lib/auth-context";
import { DashboardSkeleton } from "@/components/ui/skeleton";

/**
 * Dynamically imported with ssr:false so @clerk/nextjs hooks inside
 * CloudOnboardingContent never execute on the server or in local mode.
 */
const CloudOnboardingContent = dynamic(
  () =>
    import("./onboarding-cloud").then((m) => ({
      default: m.CloudOnboardingContent,
    })),
  {
    ssr: false,
    loading: () => (
      <div className="flex items-center justify-center min-h-[60vh]">
        <Loader2 className="w-5 h-5 animate-spin text-[var(--color-text-dim)]" />
      </div>
    ),
  }
);

export default function OnboardingPage() {
  const router = useRouter();
  const { isCloudMode, isLoaded } = useAppAuth();

  useEffect(() => {
    if (isLoaded && !isCloudMode) {
      router.push("/dashboard");
    }
  }, [isLoaded, isCloudMode, router]);

  if (!isLoaded || !isCloudMode) {
    return <DashboardSkeleton />;
  }

  return <CloudOnboardingContent />;
}
