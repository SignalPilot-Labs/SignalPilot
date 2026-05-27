"use client";

import { useEffect, useRef, useState } from "react";
import { Loader2 } from "lucide-react";
import {
  createSignalpilotClient,
  SignalpilotEditor,
  type SignalpilotClient,
} from "@/embed";
import { useNotebookConfig } from "./notebook-context";

type BootPhase = "health" | "syncing" | "sessions" | "ready";

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
  const [phase, setPhase] = useState<BootPhase>("health");
  const [error, setError] = useState<string | null>(null);
  const clientRef = useRef<SignalpilotClient | null>(null);
  const [ready, setReady] = useState(false);

  useEffect(() => {
    let cancelled = false;

    async function boot() {
      const runtimeUrl = `${config.gatewayUrl}/notebook/${config.sessionId}`;
      const headers: Record<string, string> = {
        Authorization: `Bearer ${config.token}`,
        "Content-Type": "application/json",
      };

      // Step 1: Wait for runtime healthy
      setPhase("health");
      let healthy = false;
      for (let i = 0; i < 30 && !cancelled; i++) {
        try {
          const r = await fetch(`${runtimeUrl}/health`, { headers });
          if (r.ok) {
            healthy = true;
            break;
          }
        } catch {
          /* retry */
        }
        await new Promise((r) => setTimeout(r, 500));
      }
      if (cancelled) return;
      if (!healthy) {
        setError("Runtime did not become healthy after 15 seconds");
        return;
      }

      // Step 2: Sync project files if project specified
      if (config.project) {
        setPhase("syncing");
        try {
          await fetch(`${runtimeUrl}/api/project/sync-down`, {
            method: "POST",
            headers: {
              ...headers,
              "X-Gateway-Project-Id": config.project,
              ...(config.branch
                ? { "X-Gateway-Branch-Id": config.branch }
                : {}),
            },
          });
        } catch {
          /* sync failure is non-fatal */
        }
      }
      if (cancelled) return;

      // Step 3: Check for an existing session we can reuse.
      // If the pod already has a session for our file, the notebook should
      // reconnect to it instead of creating a new one (which would be rejected
      // with SP_ALREADY_CONNECTED).
      // Step 3: Find an existing session for our file and take it over.
      // The takeover disconnects any stale WebSocket from a previous page
      // load so our new connection won't be rejected with SP_ALREADY_CONNECTED.
      setPhase("sessions");
      try {
        const sessResp = await fetch(`${runtimeUrl}/api/sessions`, { headers });
        if (sessResp.ok) {
          const sessions = (await sessResp.json()) as Record<string, { filename?: string | null }>;
          let existingSessionId: string | undefined;
          if (config.file) {
            for (const [sid, info] of Object.entries(sessions)) {
              if (info.filename && info.filename.endsWith(config.file)) {
                existingSessionId = sid;
                break;
              }
            }
          }
          if (existingSessionId || Object.keys(sessions).length > 0) {
            await fetch(`${runtimeUrl}/api/kernel/takeover`, {
              method: "POST",
              headers,
              body: "{}",
            }).catch(() => {});
          }
          if (existingSessionId) {
            const { setSessionId } = await import("@/core/kernel/session");
            setSessionId(existingSessionId as any);
          }
        }
      } catch {}
      if (cancelled) return;

      const client = createSignalpilotClient({
        runtimeConfig: {
          url: runtimeUrl,
          authToken: config.token,
          lazy: false,
        },
        writeDocumentTitle: false,
      });

      // The RuntimeManager was just created with lazy=false, which triggers
      // init() → health check retry loop. But we already verified health in
      // Step 1. Pre-resolve it so init() skips the redundant network calls.
      try {
        const { getRuntimeManager } = await import("@/core/runtime/config");
        getRuntimeManager().markHealthy();
      } catch {}

      clientRef.current = client;
      setPhase("ready");
      setReady(true);
    }

    boot();
    return () => {
      cancelled = true;
      if (clientRef.current) {
        try {
          clientRef.current.dispose();
        } catch {
          /* ignore */
        }
        clientRef.current = null;
      }
      setReady(false);
    };
  }, [config.sessionId, config.token, config.gatewayUrl, config.project, config.branch]);

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
