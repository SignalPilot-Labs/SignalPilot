import type { Metadata } from "next";

export const metadata: Metadata = {
  title: "SignalPilot — Governed AI Database Access",
  description: "Secure, governed sandbox console for AI-powered database access with PII redaction, cost budgeting, and full audit trails.",
};

export default function LandingLayout({
  children,
}: {
  children: React.ReactNode;
}) {
  return (
    <div className="min-h-screen bg-[var(--color-bg)] text-[var(--color-text)] -ml-56">
      {children}
    </div>
  );
}
