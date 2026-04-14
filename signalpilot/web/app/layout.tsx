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
            <GridBackground />
            <main className="ml-56 min-h-screen relative z-10">
              <ErrorBoundary>
                <PageTransition>{children}</PageTransition>
              </ErrorBoundary>
              <KeyboardShortcuts />
              <CommandPalette />
            </main>
          </ConnectionProvider>
        </ToastProvider>
      </body>
    </html>
  );
}
