import type { Metadata, Viewport } from "next";
import "./globals.css";
import Sidebar from "@/components/layout/sidebar";
import { ErrorBoundary } from "@/components/ui/error-boundary";
import { KeyboardShortcuts } from "@/components/ui/keyboard-shortcuts";
import { CommandPalette } from "@/components/ui/command-palette";
import { ToastProvider } from "@/components/ui/toast";
import { GridBackground } from "@/components/ui/grid-background";
import { PageTransition } from "@/components/ui/page-transition";
import { NetworkStatus } from "@/components/ui/network-status";
import { ScrollToTop } from "@/components/ui/scroll-to-top";
import { ServiceWorkerRegister } from "@/components/ui/sw-register";
import { ConnectionProvider } from "@/lib/connection-context";

export const metadata: Metadata = {
  title: "SignalPilot",
  description: "Governed sandbox console for AI database access",
  manifest: "/manifest.json",
  appleWebApp: {
    capable: true,
    statusBarStyle: "black-translucent",
    title: "SignalPilot",
  },
  icons: {
    icon: [
      { url: "/favicon.ico", sizes: "any" },
      { url: "/favicon.svg", type: "image/svg+xml" },
      { url: "/favicon-96x96.png", sizes: "96x96", type: "image/png" },
    ],
    apple: "/apple-touch-icon.png",
  },
  other: {
    "mobile-web-app-capable": "yes",
  },
};

export const viewport: Viewport = {
  width: "device-width",
  initialScale: 1,
  maximumScale: 1,
  userScalable: false,
  viewportFit: "cover",
  themeColor: "#050505",
};

export default function RootLayout({
  children,
}: {
  children: React.ReactNode;
}) {
  return (
    <html lang="en" className="dark">
      <body className="antialiased bg-noise">
        <ToastProvider>
          <ConnectionProvider>
            <Sidebar />
            <NetworkStatus />
            <GridBackground />
            <main className="main-content min-h-screen relative z-10">
              <ErrorBoundary>
                <PageTransition>{children}</PageTransition>
              </ErrorBoundary>
              <KeyboardShortcuts />
              <CommandPalette />
              <ScrollToTop />
            </main>
            <ServiceWorkerRegister />
          </ConnectionProvider>
        </ToastProvider>
      </body>
    </html>
  );
}
