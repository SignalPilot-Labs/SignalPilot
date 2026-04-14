import type { Metadata } from "next";

export const metadata: Metadata = {
  title: "Sign In — SignalPilot AutoCode",
  description: "Sign in to your AutoCode account.",
  openGraph: {
    title: "Sign In — SignalPilot AutoCode",
    description: "Sign in to your AutoCode account.",
    url: "https://autocode.signalpilot.com/signin",
  },
};

export default function SigninLayout({
  children,
}: {
  children: React.ReactNode;
}) {
  return children;
}
