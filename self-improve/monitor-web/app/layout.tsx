import type { Metadata } from "next";
import "./globals.css";

export const metadata: Metadata = {
  title: "SignalPilot \u00B7 Self-Improve Monitor",
  description: "Real-time monitoring dashboard for the self-improvement agent",
};

export default function RootLayout({
  children,
}: {
  children: React.ReactNode;
}) {
  return (
    <html lang="en" className="dark">
      <body>{children}</body>
    </html>
  );
}
