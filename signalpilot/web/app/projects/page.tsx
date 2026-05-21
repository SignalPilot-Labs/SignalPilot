"use client";

import { useEffect, useState, useRef } from "react";
import {
  Loader2,
  Code,
  ExternalLink,
  Square,
} from "lucide-react";
import {
  createNotebookSession,
  getNotebookSession,
  deleteNotebookSession,
  pingNotebookSession,
} from "@/lib/api";
import { StatusDot } from "@/components/ui/data-viz";
import { useToast } from "@/components/ui/toast";

export default function ProjectsPage() {
  const { toast } = useToast();

  const GATEWAY_URL = process.env.NEXT_PUBLIC_GATEWAY_URL ?? "http://localhost:3300";

  const [ideStatus, setIdeStatus] = useState<"closed" | "starting" | "running">("closed");
  const [ideUrl, setIdeUrl] = useState<string | null>(null);
  const [iframeLoaded, setIframeLoaded] = useState(false);
  const pingRef = useRef<ReturnType<typeof setInterval> | null>(null);

  useEffect(() => {
    checkSession();
    return () => { if (pingRef.current) clearInterval(pingRef.current); };
  }, []);

  async function checkSession() {
    try {
      const session = await getNotebookSession();
      if (session && session.status === "running" && session.notebook_url) {
        setIdeStatus("running");
        setIdeUrl(`${GATEWAY_URL}${session.notebook_url}`);
        startPing();
      }
    } catch {}
  }

  async function launchIde() {
    setIdeStatus("starting");
    setIframeLoaded(false);
    try {
      const session = await createNotebookSession({ project_id: "", branch: "main" });
      if (!session.notebook_url) {
        toast("Session created but notebook URL not available", "error");
        setIdeStatus("closed");
        return;
      }
      setIdeStatus("running");
      setIdeUrl(`${GATEWAY_URL}${session.notebook_url}`);
      startPing();
    } catch (e) {
      toast(String(e), "error");
      setIdeStatus("closed");
    }
  }

  async function launchExternal() {
    setIdeStatus("starting");
    try {
      const session = await createNotebookSession({ project_id: "", branch: "main" });
      if (session.notebook_url) {
        window.open(`${GATEWAY_URL}${session.notebook_url}`, "_blank");
      }
      setIdeStatus("closed");
    } catch (e) {
      toast(String(e), "error");
      setIdeStatus("closed");
    }
  }

  async function stopIde() {
    try { await deleteNotebookSession(); } catch {}
    setIdeStatus("closed");
    setIdeUrl(null);
    setIframeLoaded(false);
    if (pingRef.current) { clearInterval(pingRef.current); pingRef.current = null; }
  }

  function startPing() {
    if (pingRef.current) clearInterval(pingRef.current);
    pingRef.current = setInterval(async () => {
      try { await pingNotebookSession(); } catch {}
    }, 60000);
  }

  // Full-screen IDE mode
  if (ideStatus !== "closed" && (ideUrl || ideStatus === "starting")) {
    return (
      <div className="flex flex-col h-screen">
        <div className="flex items-center justify-between px-4 py-2 border-b border-[var(--color-border)] bg-[var(--color-bg)]">
          <div className="flex items-center gap-3">
            <Code className="w-4 h-4 text-[var(--color-text)]" />
            <span className="text-xs font-bold uppercase tracking-wider text-[var(--color-text)]">
              SignalPilot IDE
            </span>
            {!iframeLoaded ? (
              <>
                <Loader2 className="w-3.5 h-3.5 animate-spin text-[var(--color-text-dim)]" />
                <span className="text-[11px] text-[var(--color-text-dim)]">
                  {!ideUrl ? "starting..." : "loading..."}
                </span>
              </>
            ) : (
              <>
                <StatusDot status="healthy" size={4} pulse />
                <span className="text-[11px] text-[var(--color-success)]">running</span>
              </>
            )}
          </div>
          <div className="flex items-center gap-2">
            {ideUrl && (
              <a
                href={ideUrl}
                target="_blank"
                rel="noopener noreferrer"
                className="flex items-center gap-1.5 px-3 py-1.5 text-[11px] text-[var(--color-text-dim)] border border-[var(--color-border)] hover:border-[var(--color-text-dim)] hover:text-[var(--color-text)] transition-all tracking-wider uppercase"
              >
                <ExternalLink className="w-3 h-3" /> open external
              </a>
            )}
            <button
              onClick={() => { stopIde(); setIframeLoaded(false); }}
              className="flex items-center gap-1.5 px-3 py-1.5 text-[11px] text-[var(--color-text-dim)] border border-[var(--color-border)] hover:border-[var(--color-error)] hover:text-[var(--color-error)] transition-all tracking-wider uppercase"
            >
              <Square className="w-3 h-3" /> stop
            </button>
          </div>
        </div>
        <div className="flex-1 relative">
          {(!ideUrl || !iframeLoaded) && (
            <div className="absolute inset-0 flex flex-col items-center justify-center gap-4 bg-[var(--color-bg)] z-10">
              <Loader2 className="w-8 h-8 animate-spin text-[var(--color-text-dim)]" />
              <span className="text-xs text-[var(--color-text-dim)] tracking-wider uppercase">
                {ideStatus === "starting" ? "starting notebook pod..." : "loading IDE..."}
              </span>
            </div>
          )}
          {ideUrl && (
            <iframe
              src={ideUrl}
              title="Marimo notebook"
              className="absolute inset-0 w-full h-full border-0"
              style={{ opacity: iframeLoaded ? 1 : 0, transition: "opacity 300ms ease-in" }}
              onLoad={() => setIframeLoaded(true)}
              allow="clipboard-read; clipboard-write"
              sandbox="allow-scripts allow-same-origin allow-forms allow-downloads"
            />
          )}
        </div>
      </div>
    );
  }

  // Landing — two buttons
  return (
    <div className="p-8 animate-fade-in">
      <div className="max-w-md mx-auto mt-24">
        <div className="flex items-center gap-3 mb-8">
          <Code className="w-6 h-6 text-[var(--color-text)]" />
          <h1 className="text-lg font-bold uppercase tracking-wider text-[var(--color-text)]">
            SignalPilot IDE
          </h1>
        </div>

        <div className="space-y-3">
          <button
            onClick={launchIde}
            className="w-full flex items-center gap-3 px-5 py-4 bg-[var(--color-text)] text-[var(--color-bg)] text-xs font-medium tracking-wider uppercase transition-all hover:opacity-90"
          >
            <Code className="w-4 h-4" />
            <span>open IDE</span>
          </button>

          <button
            onClick={launchExternal}
            className="w-full flex items-center gap-3 px-5 py-4 text-xs text-[var(--color-text-dim)] border border-[var(--color-border)] hover:border-[var(--color-text-dim)] hover:text-[var(--color-text)] transition-all tracking-wider uppercase"
          >
            <ExternalLink className="w-4 h-4" />
            <span>open in new tab</span>
          </button>
        </div>
      </div>
    </div>
  );
}
