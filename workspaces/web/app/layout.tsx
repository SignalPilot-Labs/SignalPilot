import type { Metadata } from "next";
import "./globals.css";
import { ClerkProvider } from "@clerk/nextjs";
import { getServerEnv } from "@/lib/env";
import Sidebar from "@/components/layout/Sidebar";
import { MainContent } from "@/components/layout/MainContent";
import { GridBackground } from "@/components/ui/GridBackground";
import { ToastProvider } from "@/components/ui/Toast";

export const metadata: Metadata = {
  title: "Workspaces",
  description: "Workspace chart dashboards",
};

export default function RootLayout({
  children,
}: {
  children: React.ReactNode;
}) {
  const env = getServerEnv();
  const body = (
    <body className="antialiased bg-noise font-mono">
      <ToastProvider>
        <Sidebar />
        <GridBackground />
        <MainContent>{children}</MainContent>
      </ToastProvider>
    </body>
  );
  if (env.mode === "cloud") {
    return (
      <html lang="en">
        <ClerkProvider>{body}</ClerkProvider>
      </html>
    );
  }
  return <html lang="en">{body}</html>;
}
