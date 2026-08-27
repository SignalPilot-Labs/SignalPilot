import { useAtomValue, useSetAtom } from "jotai";
import {
  AlertTriangleIcon,
  CheckIcon,
  RotateCcwIcon,
  XIcon,
  ZapIcon,
} from "lucide-react";
import React, { useEffect, useState } from "react";
import { Spinner } from "@/components/icons/spinner";
import { Button } from "@/components/ui/button";
import {
  dismissKernelLaunchError,
  isKernelLaunchInFlight,
  type KernelLaunchPhase,
  kernelLaunchAtom,
  launchRuntime,
} from "@/core/runtime/launch-state";
import { cn } from "@/utils/cn";

/**
 * Kernel status island — the one place the user watches a kernel come up.
 *
 * Floats bottom-right (out of the reading line, near the footer's kernel
 * chip) instead of banner-ing over the notebook. Shows honest staged
 * progress: what is happening right now, how long it has been, and why the
 * first run takes a moment. Background prewarms render as a quiet one-liner;
 * explicit runs get the full staged card; failures get a retry.
 */

const STEPS: Array<{ phase: KernelLaunchPhase; label: string }> = [
  { phase: "provisioning", label: "Spinning up a secure sandbox" },
  { phase: "connecting", label: "Linking your notebook" },
  { phase: "starting", label: "Warming the Python kernel" },
];

const PHASE_ORDER: Record<string, number> = {
  provisioning: 0,
  connecting: 1,
  starting: 2,
  ready: 3,
};

/** Time-eased progress: asymptotic toward the phase ceiling so the bar
 * always moves but never lies about being done. */
function progressFor(phase: KernelLaunchPhase, elapsedMs: number): number {
  if (phase === "ready") return 100;
  const base: Record<string, [number, number]> = {
    provisioning: [4, 72],
    connecting: [76, 84],
    starting: [86, 96],
  };
  const range = base[phase];
  if (!range) return 0;
  const [from, to] = range;
  // ~63% of the phase's range after 5s, ~86% after 10s.
  const eased = 1 - Math.exp(-elapsedMs / 5000);
  return from + (to - from) * eased;
}

function useElapsedMs(startedAt: number | null, active: boolean): number {
  const [now, setNow] = useState(() => Date.now());
  useEffect(() => {
    if (!active) return;
    const id = setInterval(() => setNow(Date.now()), 200);
    return () => clearInterval(id);
  }, [active]);
  if (startedAt == null) return 0;
  return Math.max(0, now - startedAt);
}

export const KernelStatusIsland: React.FC = () => {
  const launch = useAtomValue(kernelLaunchAtom);
  const setLaunch = useSetAtom(kernelLaunchAtom);
  const inFlight = isKernelLaunchInFlight(launch);
  const elapsedMs = useElapsedMs(launch.startedAt, inFlight);

  if (launch.phase === "idle") {
    return null;
  }

  // Quiet variant for background prewarm: a whisper, not an announcement.
  if (launch.trigger === "prewarm" && launch.phase !== "error") {
    return (
      <Shell subtle>
        {launch.phase === "ready" ? (
          <ReadyRow label="Kernel ready" sublabel="Your first run will start instantly." />
        ) : (
          <div className="flex items-center gap-2.5 px-3.5 py-2.5">
            <Spinner size="small" className="text-muted-foreground shrink-0" />
            <div className="min-w-0">
              <p className="text-xs font-medium text-foreground">
                Preparing your kernel
              </p>
              <p className="text-[11px] text-muted-foreground truncate">
                Warming a sandbox in the background — runs will be instant.
              </p>
            </div>
          </div>
        )}
      </Shell>
    );
  }

  if (launch.phase === "error") {
    return (
      <Shell>
        <div className="flex items-start gap-3 px-4 py-3.5">
          <span className="mt-0.5 flex size-7 shrink-0 items-center justify-center rounded-md bg-(--red-3) text-(--red-11)">
            <AlertTriangleIcon className="size-4" />
          </span>
          <div className="min-w-0 flex-1">
            <p className="text-sm font-medium text-foreground">
              Couldn’t start the kernel
            </p>
            {launch.error && (
              <p className="mt-0.5 line-clamp-2 text-xs text-muted-foreground">
                {launch.error}
              </p>
            )}
            <Button
              size="xs"
              variant="secondary"
              className="mt-2 h-7 gap-1.5"
              onClick={() => void launchRuntime("manual").catch(() => {})}
            >
              <RotateCcwIcon className="size-3" />
              Try again
            </Button>
          </div>
          <button
            type="button"
            aria-label="Dismiss"
            className="rounded p-1 text-muted-foreground hover:bg-accent hover:text-foreground"
            onClick={dismissKernelLaunchError}
          >
            <XIcon className="size-3.5" />
          </button>
        </div>
      </Shell>
    );
  }

  if (launch.phase === "ready") {
    return (
      <Shell>
        <ReadyRow
          label="Kernel ready"
          sublabel={
            launch.trigger === "run" ? "Running your cells…" : "Connected."
          }
        />
      </Shell>
    );
  }

  // Full staged card for run / manual launches.
  const activeIndex = PHASE_ORDER[launch.phase] ?? 0;
  const progress = progressFor(launch.phase, elapsedMs);
  const seconds = elapsedMs / 1000;

  return (
    <Shell>
      {/* Progress hairline along the top edge of the card */}
      <div className="h-0.5 w-full overflow-hidden rounded-t-xl bg-muted">
        <div
          className="h-full rounded-r-full bg-primary transition-[width] duration-300 ease-out"
          style={{ width: `${progress}%` }}
        />
      </div>
      <div className="px-4 pt-3 pb-3.5">
        <div className="flex items-center gap-2.5">
          <span className="flex size-7 shrink-0 items-center justify-center rounded-md bg-primary/10 text-primary">
            <ZapIcon className="size-4" />
          </span>
          <div className="min-w-0 flex-1">
            <p className="text-sm font-medium text-foreground">
              {launch.trigger === "run"
                ? "Starting your kernel"
                : "Connecting to a kernel"}
            </p>
          </div>
          <span className="text-[11px] tabular-nums text-muted-foreground">
            {seconds.toFixed(0)}s
          </span>
        </div>

        <ol className="mt-3 flex flex-col gap-1.5">
          {STEPS.map((step, i) => {
            const state =
              i < activeIndex ? "done" : i === activeIndex ? "active" : "todo";
            return (
              <li key={step.phase} className="flex items-center gap-2.5">
                <span className="flex size-4 shrink-0 items-center justify-center">
                  {state === "done" && (
                    <CheckIcon className="size-3.5 text-(--grass-9)" />
                  )}
                  {state === "active" && (
                    <Spinner size="small" className="size-3.5 text-primary" />
                  )}
                  {state === "todo" && (
                    <span className="size-1.5 rounded-full bg-border" />
                  )}
                </span>
                <span
                  className={cn(
                    "text-xs",
                    state === "active" && "text-foreground",
                    state === "done" && "text-muted-foreground line-through decoration-transparent",
                    state === "todo" && "text-muted-foreground/60",
                  )}
                >
                  {step.label}
                </span>
              </li>
            );
          })}
        </ol>

        <p className="mt-3 border-t border-border pt-2.5 text-[11px] leading-relaxed text-muted-foreground">
          Your code runs on an isolated cloud sandbox. The first run boots a
          fresh one — usually under ten seconds — then it stays warm, so the
          next runs are instant.
        </p>
      </div>
    </Shell>
  );
};

const Shell: React.FC<{ subtle?: boolean; children: React.ReactNode }> = ({
  subtle,
  children,
}) => (
  <div
    data-testid="kernel-status-island"
    className={cn(
      // right-20 keeps clear of the floating action rail hugging the right edge
      "fixed bottom-14 right-20 z-100 overflow-hidden rounded-xl border border-border bg-background/95 shadow-lg backdrop-blur-md",
      "animate-in fade-in slide-in-from-bottom-3 duration-300",
      "print:hidden",
      subtle ? "w-[310px]" : "w-[330px]",
    )}
  >
    {children}
  </div>
);

const ReadyRow: React.FC<{ label: string; sublabel: string }> = ({
  label,
  sublabel,
}) => (
  <div className="flex items-center gap-2.5 px-3.5 py-2.5">
    <span className="flex size-6 shrink-0 items-center justify-center rounded-full bg-(--grass-3) text-(--grass-11)">
      <CheckIcon className="size-3.5" />
    </span>
    <div className="min-w-0">
      <p className="text-xs font-medium text-foreground">{label}</p>
      <p className="text-[11px] text-muted-foreground truncate">{sublabel}</p>
    </div>
  </div>
);
