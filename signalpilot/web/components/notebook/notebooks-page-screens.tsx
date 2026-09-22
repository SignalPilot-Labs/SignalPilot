"use client";

import { Code, ExternalLink, Loader2 } from "lucide-react";

export function IDEHeader({
  children,
  right,
}: {
  children?: React.ReactNode;
  right?: React.ReactNode;
}) {
  return (
    <div className="flex items-center justify-between px-4 py-2 border-b border-border bg-background">
      <div className="flex items-center gap-3">
        <Code className="w-4 h-4 text-foreground" />
        <span className="text-xs font-bold uppercase tracking-wider text-foreground">
          SignalPilot notebook
        </span>
        {children}
      </div>
      {right && <div className="flex items-center gap-2">{right}</div>}
    </div>
  );
}

export function NotebookLoadingScreen({ launchStatus }: { launchStatus: string }) {
  return (
    <div className="flex flex-col h-screen bg-background text-foreground">
      <IDEHeader>
        <Loader2 className="w-3.5 h-3.5 animate-spin text-muted-foreground" />
        <span className="text-[11px] text-muted-foreground">{launchStatus}</span>
      </IDEHeader>
      <div className="flex-1 flex flex-col items-center justify-center gap-4">
        <Loader2 className="w-8 h-8 animate-spin text-muted-foreground" />
        <span className="text-xs text-muted-foreground tracking-wider uppercase">
          {launchStatus}
        </span>
      </div>
    </div>
  );
}

export function NotebookLandingScreen({ onLaunch }: { onLaunch: () => void }) {
  return (
    <div className="p-8 animate-fade-in">
      <div className="max-w-6xl mx-auto mt-16">
        <div className="flex items-center gap-3 mb-6">
          <Code className="w-6 h-6 text-foreground" />
          <h1 className="text-lg font-bold uppercase tracking-wider text-foreground">
            SignalPilot IDE
          </h1>
        </div>
        <div className="flex flex-wrap items-center gap-3 mb-8">
          <button
            onClick={onLaunch}
            className="flex items-center gap-3 px-5 py-3 bg-primary text-primary-foreground text-xs font-medium tracking-wider uppercase transition-all hover:opacity-90"
          >
            <Code className="w-4 h-4" />
            <span>open notebook runtime</span>
          </button>
          <a
            href="/projects"
            className="flex items-center gap-3 px-5 py-3 text-xs text-muted-foreground border border-border hover:border-muted-foreground hover:text-foreground transition-all tracking-wider uppercase"
          >
            <ExternalLink className="w-4 h-4" />
            <span>back to projects</span>
          </a>
        </div>
      </div>
    </div>
  );
}
