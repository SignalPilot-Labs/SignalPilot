"use client";

import { useEffect, useRef, useState, useCallback } from "react";
import { useRouter } from "next/navigation";
import { Loader2 } from "lucide-react";
import { SignalpilotEditor, type SignalpilotClient } from "@/embed";
import { spaNavigate } from "@/core/router/spa-navigate";
import { useNotebookConfig } from "./notebook-context";
import {
  NotebookBootUserError,
  bootRuntime,
  type NotebookStaticData,
} from "./boot-runtime";

const PHASE_LABELS: Record<string, string> = {
  health: "starting runtime...",
  notion: "loading trail...",
  syncing: "syncing project files...",
  sessions: "connecting kernel...",
  ready: "loading notebook...",
};

function LoadingSpinner({ phase }: { phase: string }) {
  return (
    <div className="flex-1 flex flex-col items-center justify-center gap-4">
      <Loader2 className="w-8 h-8 animate-spin text-[var(--color-text-dim)]" />
      <span className="text-xs text-[var(--color-text-dim)] tracking-wider uppercase">
        {PHASE_LABELS[phase] ?? "loading notebook..."}
      </span>
    </div>
  );
}

export default function NotebookBoot({
  children,
  onPhaseChange,
  onReady,
}: {
  children?: React.ReactNode;
  onPhaseChange?: (phase: string) => void;
  onReady?: () => void;
}) {
  const config = useNotebookConfig();
  const router = useRouter();
  const [error, setError] = useState<string | null>(null);
  const clientRef = useRef<SignalpilotClient | null>(null);
  const staticDataRef = useRef<NotebookStaticData | null>(null);
  const [ready, setReady] = useState(false);
  const [phase, setPhase] = useState<string>("health");

  const onReadyRef = useRef<(() => void) | undefined>(undefined);
  useEffect(() => {
    onReadyRef.current = onReady;
  }, [onReady]);

  const onPhaseChangeRef = useRef<((phase: string) => void) | undefined>(undefined);
  useEffect(() => {
    onPhaseChangeRef.current = onPhaseChange;
  }, [onPhaseChange]);

  const handlePhase = useCallback((p: string) => {
    setPhase(p);
    onPhaseChangeRef.current?.(p);
  }, []);

  const hostNavigate = useCallback((href: string) => {
    try {
      const next = new URL(href, window.location.origin);
      const current = new URL(window.location.href);
      const sameProject = next.searchParams.get("project") === current.searchParams.get("project");
      const newFile = next.searchParams.get("file");

      if (newFile && newFile !== "__new__project" && sameProject) {
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

    bootRuntime(config, handlePhase, hostNavigate, controller.signal)
      .then((result) => {
        clientRef.current = result.client;
        staticDataRef.current = result.staticData ?? { filename: config.file };
        setReady(true);
        onReadyRef.current?.();
      })
      .catch((err) => {
        if (!controller.signal.aborted) {
          // Log the raw server error for debugging but do not surface it in the
          // UI — error bodies can contain internal paths, stack traces, or other
          // sensitive details that should not be shown to end users.
          console.error("[NotebookBoot] Failed to load notebook:", err);
          setError(
            err instanceof NotebookBootUserError
              ? err.message
              : "Failed to load notebook",
          );
        }
      });

    return () => {
      controller.abort();
      if (clientRef.current) {
        try { clientRef.current.dispose(); } catch { /* disposal is best-effort */ }
        clientRef.current = null;
      }
      staticDataRef.current = null;
      setReady(false);
    };
  }, [
    config.sessionId,
    config.kernelSessionId,
    config.getToken,
    config.gatewayUrl,
    config.notebookProxyUrl,
    config.file,
    config.project,
    config.branch,
    hostNavigate,
    handlePhase,
  ]);

  if (error) {
    return (
      <div className="flex-1 flex items-center justify-center text-[var(--color-error)] text-xs">
        {error}
      </div>
    );
  }

  if (!ready || !clientRef.current || !staticDataRef.current) {
    return <LoadingSpinner phase={phase} />;
  }

  const staticData = staticDataRef.current;

  return (
    <>
      <SignalpilotEditor
        client={clientRef.current}
        config={{
          gatewayUrl: config.gatewayUrl,
          gatewayApiKey: staticData.gatewayToken,
          filename: staticData.filename,
          initialCode: staticData.code,
          session: staticData.session,
          notebook: staticData.notebook,
        }}
        className="h-full"
      />
      {children}
    </>
  );
}
