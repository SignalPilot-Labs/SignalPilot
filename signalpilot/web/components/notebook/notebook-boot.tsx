"use client";

import { useEffect, useRef, useState, useCallback } from "react";
import { useRouter } from "next/navigation";
import { Loader2 } from "lucide-react";
import { SignalpilotEditor, type SignalpilotClient } from "@/embed";
import { spaNavigate } from "@/core/router/spa-navigate";
import { useNotebookConfig } from "./notebook-context";
import { bootRuntime, type BootPhase } from "./boot-runtime";

const PHASE_LABELS: Record<BootPhase, string> = {
  health: "waiting for runtime...",
  syncing: "syncing project files...",
  sessions: "clearing stale sessions...",
  ready: "",
};

function LoadingSpinner({ phase }: { phase: BootPhase }) {
  return (
    <div className="flex-1 flex flex-col items-center justify-center gap-4">
      <Loader2 className="w-8 h-8 animate-spin text-[var(--color-text-dim)]" />
      <span className="text-xs text-[var(--color-text-dim)] tracking-wider uppercase">
        {PHASE_LABELS[phase]}
      </span>
    </div>
  );
}

export default function NotebookBoot({
  children,
}: {
  children?: React.ReactNode;
}) {
  const config = useNotebookConfig();
  const router = useRouter();
  const [phase, setPhase] = useState<BootPhase>("health");
  const [error, setError] = useState<string | null>(null);
  const clientRef = useRef<SignalpilotClient | null>(null);
  const [ready, setReady] = useState(false);

  const hostNavigate = useCallback((href: string) => {
    try {
      const next = new URL(href, window.location.origin);
      const current = new URL(window.location.href);
      const sameProject = next.searchParams.get("project") === current.searchParams.get("project");
      const newFile = next.searchParams.get("file");

      if (sameProject && newFile && newFile !== "__new__project") {
        spaNavigate(href);
      } else {
        router.push(href);
      }
    } catch {
      router.push(href);
    }
  }, [router]);

  useEffect(() => {
    const controller = new AbortController();

    bootRuntime(config, setPhase, hostNavigate, controller.signal)
      .then((result) => {
        clientRef.current = result.client;
        setReady(true);
      })
      .catch((err) => {
        if (!controller.signal.aborted) {
          setError(err instanceof Error ? err.message : String(err));
        }
      });

    return () => {
      controller.abort();
      if (clientRef.current) {
        try { clientRef.current.dispose(); } catch { /* disposal is best-effort */ }
        clientRef.current = null;
      }
      setReady(false);
    };
  }, [config.sessionId, config.token, config.gatewayUrl, config.project, config.branch, hostNavigate]);

  if (error) {
    return (
      <div className="flex-1 flex items-center justify-center text-[var(--color-error)] text-xs">
        {error}
      </div>
    );
  }

  if (!ready || !clientRef.current) {
    return <LoadingSpinner phase={phase} />;
  }

  return (
    <>
      <SignalpilotEditor
        client={clientRef.current}
        config={{
          gatewayUrl: config.gatewayUrl,
          gatewayApiKey: config.apiKey,
        }}
        className="h-full"
      />
      {children}
    </>
  );
}
