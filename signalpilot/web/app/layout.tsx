import type { Metadata } from "next";
import "./globals.css";
import Sidebar from "@/components/layout/sidebar";
import { ErrorBoundary } from "@/components/ui/error-boundary";
import { KeyboardShortcuts } from "@/components/ui/keyboard-shortcuts";
import { CommandPalette } from "@/components/ui/command-palette";
import { ToastProvider } from "@/components/ui/toast";
import { GridBackground } from "@/components/ui/grid-background";
import { PageTransition } from "@/components/ui/page-transition";

export const metadata: Metadata = {
  title: "SignalPilot",
  description: "Governed sandbox console for AI database access",
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
          <Sidebar />
          <GridBackground />
          <main className="ml-56 min-h-screen relative z-10">
            <ErrorBoundary>
              <PageTransition>{children}</PageTransition>
            </ErrorBoundary>
            <KeyboardShortcuts />
            <CommandPalette />
          </main>
        </ToastProvider>
      </body>
    </html>
  );
}
