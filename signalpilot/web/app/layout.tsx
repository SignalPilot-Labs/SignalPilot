import type { Metadata } from "next";
import "./globals.css";
import Sidebar from "@/components/layout/sidebar";

import { ErrorBoundary } from "@/components/ui/error-boundary";
import { KeyboardShortcuts } from "@/components/ui/keyboard-shortcuts";
import { TabTitle } from "@/components/layout/tab-title";
import { CommandPalette } from "@/components/ui/command-palette";
import { ToastProvider } from "@/components/ui/toast";
import { GridBackground } from "@/components/ui/grid-background";
import { PageTransition } from "@/components/ui/page-transition";
import { MainContent } from "@/components/layout/main-content";
import { ConnectionProvider } from "@/lib/connection-context";
import { AuthProvider } from "@/lib/auth-context";
import { SWRProvider } from "@/lib/swr";
import { SubscriptionProvider } from "@/lib/subscription-context";
import { clerkAppearance } from "@/lib/clerk-theme";
import TierUpgradeCelebration from "@/components/branding/tier-upgrade-celebration";

export const metadata: Metadata = {
  title: "SignalPilot",
  description: "Governed sandbox console for AI database access",
  icons: {
    icon: [
      { url: "/favicon.ico", sizes: "any" },
      { url: "/favicon.svg", type: "image/svg+xml" },
      { url: "/favicon-96x96.png", sizes: "96x96", type: "image/png" },
    ],
    apple: "/apple-touch-icon.png",
  },
};

const isCloudMode = process.env.NEXT_PUBLIC_DEPLOYMENT_MODE === "cloud";
const clerkEnabled = isCloudMode;

export default async function RootLayout({
  children,
}: {
  children: React.ReactNode;
}) {
  const content = (
    <SWRProvider>
    <ToastProvider>
      <ConnectionProvider>
        <AuthProvider clerkEnabled={clerkEnabled}>
          <SubscriptionProvider>
            <Sidebar />
            <GridBackground />
            <MainContent>
              <ErrorBoundary>
                <PageTransition>{children}</PageTransition>
              </ErrorBoundary>
              <KeyboardShortcuts />
              <TabTitle />
              <CommandPalette />
            </MainContent>
            <TierUpgradeCelebration />
          </SubscriptionProvider>
        </AuthProvider>
      </ConnectionProvider>
    </ToastProvider>
    </SWRProvider>
  );

  if (clerkEnabled) {
    const { ClerkProvider } = await import("@clerk/nextjs");
    return (
      <html lang="en" className="dark">
        <body className="antialiased bg-noise">
          <ClerkProvider
            signInUrl="/sign-in"
            signUpUrl="/sign-up"
            signInFallbackRedirectUrl="/dashboard"
            signUpFallbackRedirectUrl="/onboarding"
            afterSignOutUrl="/"
            appearance={clerkAppearance}
          >
            {content}
          </ClerkProvider>
        </body>
      </html>
    );
  }

  return (
    <html lang="en" className="dark">
      <body className="antialiased bg-noise">{content}</body>
    </html>
  );
}
