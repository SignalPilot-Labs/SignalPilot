import type { Metadata } from "next";

export const metadata: Metadata = {
  title: "Setup — SignalPilot AutoCode",
  description: "Install the CLI, connect your repo, and run your first autonomous code improvement in under 5 minutes.",
  openGraph: {
    title: "Setup — SignalPilot AutoCode",
    description: "Install the CLI, connect your repo, and run your first autonomous code improvement in under 5 minutes.",
    url: "https://autocode.signalpilot.com/setup",
  },
};

export default function SetupLayout({
  children,
}: {
  children: React.ReactNode;
}) {
  return children;
}
