import type { Metadata } from "next";
import "./globals.css";
import Sidebar from "@/components/layout/sidebar";
import { ErrorBoundary } from "@/components/ui/error-boundary";
import { KeyboardShortcuts } from "@/components/ui/keyboard-shortcuts";
import { CommandPalette } from "@/components/ui/command-palette";

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
        <Sidebar />
        <main className="ml-56 min-h-screen bg-dots">
          <ErrorBoundary>{children}</ErrorBoundary>
          <KeyboardShortcuts />
          <CommandPalette />
        </main>
      </body>
    </html>
  );
}
