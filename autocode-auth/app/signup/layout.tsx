import type { Metadata } from "next";

export const metadata: Metadata = {
  title: "Sign Up — SignalPilot AutoCode",
  description: "Create your AutoCode account. Connect your GitHub repos and let AI ship improvements autonomously.",
  openGraph: {
    title: "Sign Up — SignalPilot AutoCode",
    description: "Create your AutoCode account. Connect your GitHub repos and let AI ship improvements autonomously.",
    url: "https://autocode.signalpilot.com/signup",
  },
};

export default function SignupLayout({
  children,
}: {
  children: React.ReactNode;
}) {
  return children;
}
