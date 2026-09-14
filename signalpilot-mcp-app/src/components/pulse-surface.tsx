import { useEffect, useMemo, useRef, useState } from "react";
import { hostAbilities, type HostAbilities } from "../bridge";
import { derivePulse } from "../pulse-state";
import type { Phase, PulseState } from "../types";
import { useRunView } from "../use-run-view";
import { Footer, useElapsed } from "./footer";
import { Orb } from "./orb";
import { PlanRail } from "./plan-rail";
import { PulseLine } from "./pulse-line";
import { Thoughts } from "./thoughts";
import { TraceStrip } from "./trace-strip";

const EYEBROW: Record<Phase, string> = {
  booting: "Starting",
  thinking: "Thinking",
  tool: "Working",
  writing: "Writing",
  waiting: "Needs you",
  completed: "Done",
  failed: "Stopped",
  cancelled: "Cancelled",
};

const PEEK_MS = 2500;
const NO_ABILITIES: HostAbilities = { displayModes: [] };

type ZoneView = "thoughts" | "stats" | "detail";

export function PulseSurface() {
  const { view, error, connected } = useRunView();
  const state = useMemo(() => (view ? derivePulse(view) : null), [view]);
  const [abilities, setAbilities] = useState<HostAbilities>(NO_ABILITIES);
  useEffect(() => {
    if (connected) setAbilities(hostAbilities());
  }, [connected]);

  if (!view || !state) {
    return (
      <main className="pulse" data-phase="booting" data-view="thoughts">
        <p className="boot-text" role="status">{error || "Connecting to SignalPilot…"}</p>
      </main>
    );
  }
  return (
    <Surface
      state={state}
      abilities={abilities}
      pollError={error}
      elapsedSeconds={view.elapsed_seconds}
      receivedAt={view.received_at}
      lastEventAt={view.events.at(-1)?.created_at ?? null}
    />
  );
}

function Surface({
  state,
  abilities,
  pollError,
  elapsedSeconds,
  receivedAt,
  lastEventAt,
}: {
  state: PulseState;
  abilities: HostAbilities;
  pollError: string;
  elapsedSeconds: number | undefined;
  receivedAt: number;
  lastEventAt: string | null;
}) {
  const { phase } = state;
  const terminal = phase === "completed" || phase === "failed" || phase === "cancelled";
  const [zone, setZone] = useState<ZoneView>("thoughts");
  const [override, setOverride] = useState<string | null>(null);
  const peekTimer = useRef<ReturnType<typeof setTimeout>>(undefined);
  const elapsedMs = useElapsed(elapsedSeconds, receivedAt, terminal || phase === "waiting");

  const notice = (message: string) => {
    clearTimeout(peekTimer.current);
    setOverride(message);
    peekTimer.current = setTimeout(() => setOverride(null), PEEK_MS);
  };
  useEffect(() => () => clearTimeout(peekTimer.current), []);
  useEffect(() => {
    if (phase !== "failed" && zone === "detail") setZone("thoughts");
  }, [phase, zone]);

  // Server timestamps are placed on the client clock via the offset of the
  // newest event against the moment its page arrived.
  const skewMs = useMemo(() => {
    const stamp = lastEventAt ? Date.parse(lastEventAt) : NaN;
    if (!Number.isFinite(stamp)) return 0;
    const skew = receivedAt - stamp;
    return Math.abs(skew) < 86_400_000 ? skew : 0;
  }, [lastEventAt, receivedAt]);

  const nowText = override ?? state.now;
  const effectiveZone: ZoneView = phase === "waiting" ? "thoughts" : zone;
  const emptyThought = phase === "booting" || phase === "thinking" ? "Waiting for the first thought" : terminal ? "No narration was streamed" : "";

  return (
    <main className="pulse" data-phase={phase} data-view={effectiveZone} aria-label="SignalPilot agent activity">
      <div className="top" data-rail={state.planItems.length > 0 ? "true" : "false"}>
        <Orb
          phase={phase}
          plan={state.plan}
          label={zone === "stats" ? "Show thoughts" : "Show run statistics"}
          onClick={() => {
            if (phase === "waiting") return;
            setZone((current) => (current === "stats" ? "thoughts" : "stats"));
          }}
        />
        <div className="body">
          <div className="eyebrow">
            <span className="dot" aria-hidden />
            <span>{EYEBROW[phase]}</span>
          </div>
          <div className="now" role="status">
            <span key={nowText}>{nowText}</span>
          </div>
          <div className="zone">
            {effectiveZone === "thoughts" && phase !== "waiting" && (
              <Thoughts thoughts={state.thoughts} writing={phase === "writing"} empty={emptyThought} />
            )}
            {phase === "waiting" && (
              <div className="question-wrap">
                <p className="question">{state.question ?? "SignalPilot needs your input."}</p>
                <p className="hint">Reply to your assistant to continue.</p>
              </div>
            )}
            {effectiveZone === "stats" && (
              <div className="stats">
                <Stat label="Tools" value={String(state.counts.tools)} />
                <Stat label="Rows read" value={state.counts.rows.toLocaleString("en-US")} mint />
                <Stat label="Elapsed" value={formatElapsed(elapsedMs)} />
              </div>
            )}
            {effectiveZone === "detail" && (
              <pre className="detail">{state.errorDetail ?? state.error ?? "No diagnostics were recorded. Open the chat in SignalPilot for the full record."}</pre>
            )}
          </div>
        </div>
        <PlanRail items={state.planItems} />
      </div>
      <TraceStrip chips={state.chips} />
      <PulseLine chips={state.chips} phase={phase} skewMs={skewMs} endedAt={state.endedAt} />
      <Footer
        phase={phase}
        counts={state.counts}
        elapsedMs={elapsedMs}
        abilities={abilities}
        detailOpen={zone === "detail"}
        onToggleDetail={() => setZone((current) => (current === "detail" ? "thoughts" : "detail"))}
        onNotice={notice}
      />
      {pollError && <p className="poll-error" role="alert">Updates paused: {pollError}</p>}
    </main>
  );
}

function Stat({ label, value, mint }: { label: string; value: string; mint?: boolean }) {
  return (
    <div className="stat">
      <small>{label}</small>
      <b className={mint ? "mint" : undefined}>{value}</b>
    </div>
  );
}

function formatElapsed(ms: number): string {
  const seconds = Math.floor(ms / 1000);
  if (seconds < 60) return `${seconds}s`;
  return `${Math.floor(seconds / 60)}m ${String(seconds % 60).padStart(2, "0")}s`;
}
