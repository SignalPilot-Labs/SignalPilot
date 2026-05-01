import type { Metadata } from "next";
import "./globals.css";
import { ClerkProvider } from "@clerk/nextjs";
import { getServerEnv } from "@/lib/env";

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
  const body = <body className="antialiased">{children}</body>;
  if (env.mode === "cloud") {
    return (
      <html lang="en">
        <ClerkProvider>{body}</ClerkProvider>
      </html>
    );
  }
  return <html lang="en">{body}</html>;
}
