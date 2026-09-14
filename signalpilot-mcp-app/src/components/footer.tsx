import { Maximize2, PictureInPicture2 } from "lucide-react";
import { useEffect, useState } from "react";
import { requestDisplayMode, type HostAbilities } from "../bridge";
import { formatClock } from "../motion";
import type { Counts, Phase } from "../types";

/**
 * Timer, counts and the two view-only controls: the failure details toggle
 * and the display-mode switch. The panel never links out or sends anything;
 * the display-mode button exists only when the host offers another mode.
 */

function countsLine(counts: Counts, phase: Phase): string {
  const parts: string[] = [];
  const word = (n: number, singular: string, plural = `${singular}s`) => `${n} ${n === 1 ? singular : plural}`;
  if (counts.queries) parts.push(word(counts.queries, "query", "queries"));
  if (counts.checks) parts.push(word(counts.checks, "check"));
  if (counts.files) parts.push(word(counts.files, "file"));
  if (counts.errors) parts.push(word(counts.errors, "error"));
  if (parts.length) return parts.join(" · ");
  return phase === "booting" ? "warming up" : "no tools yet";
}

export function useElapsed(elapsedSeconds: number | undefined, receivedAt: number, frozen: boolean): number {
  const compute = () => (elapsedSeconds ?? 0) * 1000 + (frozen ? 0 : Date.now() - receivedAt);
  const [elapsed, setElapsed] = useState(compute);
  useEffect(() => {
    setElapsed(compute());
    if (frozen) return;
    const id = setInterval(() => setElapsed(compute()), 1000);
    return () => clearInterval(id);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [elapsedSeconds, receivedAt, frozen]);
  return elapsed;
}

export function Footer({
  phase,
  counts,
  elapsedMs,
  abilities,
  detailOpen,
  onToggleDetail,
  onNotice,
}: {
  phase: Phase;
  counts: Counts;
  elapsedMs: number;
  abilities: HostAbilities;
  detailOpen: boolean;
  onToggleDetail: () => void;
  onNotice: (message: string) => void;
}) {
  const [busy, setBusy] = useState(false);
  const mode = document.documentElement.dataset.displayMode ?? "inline";
  const altMode = mode === "inline" ? (abilities.displayModes.includes("pip") ? "pip" : abilities.displayModes.includes("fullscreen") ? "fullscreen" : null) : "inline";
  return (
    <div className="foot">
      <span className="time">{formatClock(elapsedMs)}</span>
      <span className="sep">·</span>
      <span className="counts">{countsLine(counts, phase)}</span>
      <span className="grow" />
      {phase === "failed" && (
        <button type="button" className="act" onClick={onToggleDetail} aria-expanded={detailOpen}>
          {detailOpen ? "Hide details" : "Show details"}
        </button>
      )}
      {altMode && (
        <button
          type="button"
          className="act icon"
          disabled={busy}
          aria-label={altMode === "inline" ? "Back to inline" : altMode === "pip" ? "Picture-in-picture" : "Fullscreen"}
          title={altMode === "inline" ? "Back to inline" : altMode === "pip" ? "Picture-in-picture" : "Fullscreen"}
          onClick={() => {
            setBusy(true);
            void requestDisplayMode(altMode).then((granted) => {
              setBusy(false);
              if (granted) document.documentElement.dataset.displayMode = granted;
              if (granted !== altMode) onNotice("The host kept the current view");
            });
          }}
        >
          {altMode === "pip" ? <PictureInPicture2 aria-hidden /> : <Maximize2 aria-hidden />}
        </button>
      )}
    </div>
  );
}
