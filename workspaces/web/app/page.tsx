import { PageHeader } from "@/components/ui/PageHeader";
import { TerminalBar } from "@/components/ui/PageHeader";
import Link from "next/link";

export default function HomePage() {
  return (
    <div className="p-8 max-w-[1400px] animate-fade-in">
      <PageHeader
        title="workspaces"
        subtitle="home"
        description="Your workspace chart dashboards and data pipelines."
        actions={
          <Link
            href="/dashboards"
            className="text-[12px] text-[var(--color-text-muted)] hover:text-[var(--color-text)] tracking-wider uppercase transition-colors"
          >
            → dashboards
          </Link>
        }
      />
      <TerminalBar path="home" />
      <p className="text-[var(--color-text-muted)] text-sm tracking-wide">
        Browse{" "}
        <Link href="/dashboards" className="text-[var(--color-text)] hover:text-[var(--color-success)] transition-colors underline underline-offset-2">
          dashboards
        </Link>{" "}
        to view charts for a workspace.
      </p>
    </div>
  );
}
