import type { Metadata } from "next";
import "./globals.css";
import Sidebar from "@/components/layout/sidebar";
import { ErrorBoundary } from "@/components/ui/error-boundary";
import { KeyboardShortcuts } from "@/components/ui/keyboard-shortcuts";
import { CommandPalette } from "@/components/ui/command-palette";
import { ToastProvider } from "@/components/ui/toast";
import { GridBackground } from "@/components/ui/grid-background";
import { PageTransition } from "@/components/ui/page-transition";
import { ConnectionProvider } from "@/lib/connection-context";
import { AuthProvider } from "@/lib/auth-context";
import { SubscriptionProvider } from "@/lib/subscription-context";
import { clerkAppearance } from "@/lib/clerk-theme";

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
    <ToastProvider>
      <ConnectionProvider>
        <AuthProvider clerkEnabled={clerkEnabled}>
          <SubscriptionProvider>
            <Sidebar />
            <GridBackground />
            <main className="ml-56 min-h-screen relative z-10">
              <ErrorBoundary>
                <PageTransition>{children}</PageTransition>
              </ErrorBoundary>
              <KeyboardShortcuts />
              <CommandPalette />
            </main>
          </SubscriptionProvider>
        </AuthProvider>
      </ConnectionProvider>
    </ToastProvider>
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
