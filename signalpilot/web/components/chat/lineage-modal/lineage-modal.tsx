"use client";

import { ExternalLink, Loader2, X } from "lucide-react";
import Link from "next/link";
import {
  Component,
  useCallback,
  useEffect,
  useRef,
  useState,
  type ErrorInfo,
  type ReactNode,
} from "react";
import { createPortal } from "react-dom";
import { useFocusTrap } from "~/components/ui/use-focus-trap";
import { LineageEmbed, type MapStatus } from "~/components/lineage/lineage-embed";
import type { LineageHref } from "./lineage-href";

/**
 * In-chat lineage viewer. Renders the same staged lineage view the
 * /lineage/<model> page shows, inside a near-fullscreen dialog over the chat.
 * The URL never changes; "Open full page" is the way out to the real route.
 *
 * Closes on Escape, backdrop click, or the button. Body scroll locks and
 * focus is trapped while open; focus returns to the opener on close.
 */
export function LineageModal({
  link,
  onClose,
}: {
  link: LineageHref;
  onClose: () => void;
}) {
  const [mounted, setMounted] = useState(false);
  const [status, setStatus] = useState<MapStatus>("loading");
  const [crashed, setCrashed] = useState(false);
  const panelRef = useRef<HTMLDivElement>(null);
  const restoreFocus = useRef<HTMLElement | null>(null);

  useEffect(() => setMounted(true), []);
  useFocusTrap(panelRef, mounted);

  useEffect(() => {
    restoreFocus.current = document.activeElement as HTMLElement | null;
    const onKeyDown = (event: KeyboardEvent) => {
      if (event.key !== "Escape") return;
      event.stopPropagation();
      onClose();
    };
    // Capture phase: the embedded map must not swallow Escape first.
    window.addEventListener("keydown", onKeyDown, true);
    const previousOverflow = document.body.style.overflow;
    document.body.style.overflow = "hidden";
    return () => {
      window.removeEventListener("keydown", onKeyDown, true);
      document.body.style.overflow = previousOverflow;
      restoreFocus.current?.focus?.();
    };
  }, [onClose]);

  const onStatusChange = useCallback((next: MapStatus) => setStatus(next), []);

  if (!mounted || typeof document === "undefined") return null;

  const failed = crashed || status === "error" || status === "no-projects";
  const title = link.raw ? `${link.modelName} · raw tables` : link.modelName;

  return createPortal(
    <div
      data-testid="lineage-modal-backdrop"
      className="fixed inset-0 z-[100] flex items-center justify-center bg-black/80 p-3 backdrop-blur-sm sm:p-6"
      onClick={onClose}
    >
      <div
        ref={panelRef}
        role="dialog"
        aria-modal="true"
        aria-label={`Lineage for ${link.modelName}`}
        data-testid="lineage-modal"
        className="flex h-full w-full flex-col overflow-hidden rounded-2xl border border-[var(--color-border)] bg-[var(--color-bg)] shadow-[0_24px_80px_rgba(0,0,0,0.6)]"
        onClick={(event) => event.stopPropagation()}
      >
        <header className="flex flex-none items-center gap-3 border-b border-[var(--color-border)] bg-[var(--color-bg-card)]/40 px-4 py-2.5">
          <span className="text-[10px] uppercase tracking-[0.12em] text-[var(--color-text-dim)]">
            lineage
          </span>
          <h2
            className="min-w-0 flex-1 truncate font-mono text-sm text-[var(--color-text)]"
            data-testid="lineage-modal-title"
          >
            {title}
          </h2>
          <Link
            href={link.href}
            data-testid="lineage-modal-open-page"
            className="flex h-8 flex-none items-center gap-1.5 whitespace-nowrap rounded-lg border border-[var(--color-border)] px-2.5 text-[11px] text-[var(--color-text-muted)] hover:border-[var(--color-border-hover)] hover:text-[var(--color-text)]"
          >
            <ExternalLink className="h-3 w-3" />
            Open full page
          </Link>
          <button
            type="button"
            aria-label="Close lineage"
            data-testid="lineage-modal-close"
            onClick={onClose}
            className="flex h-8 w-8 flex-none items-center justify-center rounded-lg border border-[var(--color-border)] bg-[var(--color-bg-card)] text-[var(--color-text-muted)] hover:border-[var(--color-border-hover)] hover:text-[var(--color-text)]"
          >
            <X className="h-4 w-4" />
          </button>
        </header>

        <div className="relative min-h-0 flex-1 bg-[var(--color-bg)]">
          {failed ? (
            <LineageError link={link} />
          ) : (
            <EmbedBoundary onCrash={() => setCrashed(true)}>
              <LineageEmbed
                modelName={link.modelName}
                projectId={link.projectId}
                raw={link.raw}
                onStatusChange={onStatusChange}
              />
            </EmbedBoundary>
          )}
          {!failed && status === "loading" && (
            <div
              className="pointer-events-none absolute right-4 top-3 flex items-center gap-1.5 font-mono text-[10px] text-[var(--color-text-dim)]"
              data-testid="lineage-modal-loading"
            >
              <Loader2 className="h-3 w-3 animate-spin" />
              loading lineage
            </div>
          )}
        </div>
      </div>
    </div>,
    document.body,
  );
}

function LineageError({ link }: { link: LineageHref }) {
  return (
    <div
      className="flex h-full flex-col items-center justify-center gap-3 p-6 text-center"
      data-testid="lineage-modal-error"
    >
      <p className="text-sm text-[var(--color-text)]">
        The lineage for <span className="font-mono">{link.modelName}</span> could not be
        loaded here.
      </p>
      <p className="max-w-md text-xs text-[var(--color-text-muted)]">
        The dbt map for this project is unavailable in this view. Open the full lineage
        page to retry, compile the map, or pick another project.
      </p>
      <Link
        href={link.href}
        className="flex items-center gap-1.5 rounded-lg border border-[var(--color-border)] px-3 py-1.5 text-xs text-[var(--color-text)] hover:border-[var(--color-border-hover)]"
      >
        <ExternalLink className="h-3 w-3" />
        Open full page
      </Link>
    </div>
  );
}

/** Turns a render crash inside the embedded map into the modal error state. */
class EmbedBoundary extends Component<
  { onCrash: () => void; children: ReactNode },
  { crashed: boolean }
> {
  state = { crashed: false };

  static getDerivedStateFromError() {
    return { crashed: true };
  }

  componentDidCatch(error: Error, info: ErrorInfo) {
    console.error("lineage embed crashed", error, info.componentStack);
    this.props.onCrash();
  }

  render() {
    return this.state.crashed ? null : this.props.children;
  }
}
