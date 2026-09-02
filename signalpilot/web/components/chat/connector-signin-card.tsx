"use client";

import { LogIn, RotateCcw, Settings2 } from "lucide-react";
import { useMemo, useState } from "react";
import type { StandaloneChatEvent } from "~/lib/api";
import { extractConnectorSignInRequests, type ConnectorSignInRequest } from "~/lib/chat-connector-signin";
import { useChatUi } from "~/components/chat/chat-ui-context";
import { ConnectorGlyph } from "~/components/connectors/connector-glyph";
import { useOptionalConnectors } from "~/components/connectors/connectors-context";
import { useToast } from "~/components/ui/toast";
import { FOCUS_RING } from "~/components/connectors/ui";

/**
 * "<Name> needs you to sign in" — rendered in the transcript when a run
 * hit a connector whose sign-in expired. One click opens the same sign-in
 * window as the settings page; on success the card offers Retry for the
 * run. Without a connectors provider (or when the connector can't be
 * matched), the card sends the user to Chat settings instead.
 */
function SignInCard({ request, runId }: { request: ConnectorSignInRequest; runId: string }) {
  const store = useOptionalConnectors();
  const { onRetry, openChatSettings } = useChatUi();
  const { toast } = useToast();
  const [phase, setPhase] = useState<"idle" | "signing" | "signed" | "retrying">("idle");
  const connector = useMemo(() => {
    if (!store) return null;
    const name = request.connectorName.toLowerCase();
    return (
      store.connectors.find((c) => c.slug === request.slug) ??
      store.connectors.find((c) => c.name.toLowerCase() === name) ??
      null
    );
  }, [request, store]);
  const signedIn = phase === "signed" || Boolean(connector?.my_state?.signed_in && phase !== "idle");

  const signIn = async () => {
    if (!store || !connector) {
      openChatSettings?.();
      return;
    }
    setPhase("signing");
    const result = await store.api.signIn(connector.id);
    if (result.outcome === "signed_in") {
      store.upsert({ ...connector, status: "connected", my_state: result.state });
      setPhase("signed");
      toast(`Signed in to ${connector.name}`, "success");
    } else {
      setPhase("idle");
      if (result.outcome === "blocked") window.open(result.url, "_blank", "noopener");
      else if (result.outcome === "error") toast(`The provider refused sign-in: ${result.message}`, "error", 6000);
    }
  };

  const retry = async () => {
    setPhase("retrying");
    try {
      await onRetry(runId);
    } finally {
      setPhase("signed");
    }
  };

  return (
    <section
      data-testid="connector-signin-card"
      data-connector={request.connectorName}
      aria-label={`${request.connectorName} needs you to sign in`}
      className="my-3 flex flex-wrap items-center gap-3 rounded-xl border border-[var(--color-warning)]/30 bg-[var(--color-warning)]/[0.05] px-3.5 py-3 animate-fade-in"
    >
      <ConnectorGlyph
        connector={connector ?? { name: request.connectorName, url: null, transport: "http" }}
        size={32}
      />
      <div className="min-w-0 flex-1">
        <p className="text-[13px] font-medium text-[var(--color-text)]">
          {signedIn
            ? `Signed in to ${request.connectorName}`
            : `Sign in to ${request.connectorName} to continue`}
        </p>
        <p className="text-[11.5px] text-[var(--color-text-muted)]">
          {signedIn
            ? "The agent can use it on its next try."
            : request.tool
              ? `Your sign-in expired before it could run ${request.tool}.`
              : "Your sign-in expired. The rest of the answer went on without it."}
        </p>
      </div>
      {signedIn ? (
        <button
          type="button"
          data-testid="connector-signin-retry"
          disabled={phase === "retrying"}
          onClick={() => void retry()}
          className={`inline-flex min-h-[34px] items-center gap-1.5 rounded-[var(--radius-ctl)] border border-[var(--color-border)] bg-[var(--color-bg-card)] px-3 text-[12px] font-medium text-[var(--color-text)] hover:border-[var(--color-border-hover)] disabled:opacity-50 ${FOCUS_RING}`}
        >
          <RotateCcw className="h-3.5 w-3.5" aria-hidden="true" />
          {phase === "retrying" ? "Retrying…" : "Retry"}
        </button>
      ) : (
        <>
          <button
            type="button"
            data-testid="connector-signin-button"
            disabled={phase === "signing"}
            onClick={() => void signIn()}
            className={`inline-flex min-h-[34px] items-center gap-1.5 rounded-[var(--radius-ctl)] bg-[var(--color-text)] px-3 text-[12px] font-medium text-[var(--color-bg)] hover:bg-[var(--color-accent-hover)] disabled:opacity-50 ${FOCUS_RING}`}
          >
            <LogIn className="h-3.5 w-3.5" aria-hidden="true" />
            {phase === "signing" ? "Waiting for sign-in…" : "Sign in"}
          </button>
          {openChatSettings && (
            <button
              type="button"
              aria-label="Open chat settings"
              title="Open chat settings"
              data-testid="connector-signin-settings"
              onClick={openChatSettings}
              className={`flex h-[34px] w-[34px] items-center justify-center rounded-[var(--radius-ctl)] text-[var(--color-text-dim)] hover:bg-[var(--color-bg-hover)] hover:text-[var(--color-text)] ${FOCUS_RING}`}
            >
              <Settings2 className="h-3.5 w-3.5" aria-hidden="true" />
            </button>
          )}
        </>
      )}
    </section>
  );
}

/** All sign-in cards for one run; renders nothing when there are none. */
export function ConnectorSignInCards({
  events,
  runId,
}: {
  events: StandaloneChatEvent[];
  runId: string;
}) {
  const requests = useMemo(() => extractConnectorSignInRequests(events, runId), [events, runId]);
  if (requests.length === 0) return null;
  return (
    <div data-testid="connector-signin-cards">
      {requests.map((request) => (
        <SignInCard key={request.connectorName} request={request} runId={runId} />
      ))}
    </div>
  );
}
