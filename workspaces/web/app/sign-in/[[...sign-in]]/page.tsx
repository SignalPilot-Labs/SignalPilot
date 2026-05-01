import { notFound } from "next/navigation";
import { SignIn } from "@clerk/nextjs";
import { getServerEnv } from "@/lib/env";
import { GridBackground } from "@/components/ui/GridBackground";

export default function SignInPage() {
  const env = getServerEnv();
  if (env.mode === "local") notFound();
  return (
    <div className="relative min-h-screen flex flex-col items-center justify-center p-8">
      <GridBackground />

      {/* Terminal card chrome */}
      <div className="relative z-10 w-full max-w-sm">
        {/* Header bar */}
        <div className="flex items-center gap-3 px-4 py-2 border border-b-0 border-[var(--color-border)] bg-[var(--color-bg-card)]">
          <div className="flex items-center gap-1.5">
            <span className="w-2 h-2 bg-[var(--color-text-dim)] opacity-30" />
            <span className="w-2 h-2 bg-[var(--color-text-dim)] opacity-20" />
            <span className="w-2 h-2 bg-[var(--color-text-dim)] opacity-10" />
          </div>
          <code className="text-[12px] text-[var(--color-text-dim)] tracking-wider flex-1">
            <span className="text-[var(--color-success)]">$</span>
            <span className="text-[var(--color-text-dim)]"> workspaces </span>
            <span className="text-[var(--color-text-muted)]">sign-in</span>
          </code>
        </div>

        {/* Clerk widget */}
        <div className="border border-[var(--color-border)] bg-[var(--color-bg-card)] p-6">
          {/* Brand */}
          <div className="mb-6 text-center">
            <h1 className="text-[13px] font-bold tracking-[0.2em] uppercase text-[var(--color-text)]">
              WORKSPACES
            </h1>
            <p className="text-[11px] text-[var(--color-text-dim)] tracking-[0.15em] uppercase mt-1">
              sign in to continue
            </p>
          </div>
          <SignIn />
        </div>
      </div>
    </div>
  );
}
