/**
 * Usage rendered against an included allotment (daily requests, a session
 * budget). Going past the allotment is normal: the meter fills to 100% in
 * its usual colour and the excess is reported as extra usage or extra cost,
 * never as an error.
 */

export type AllotmentSplit = {
  /** Percent of the allotment used, capped at 100 for the meter fill. */
  fillPct: number;
  /** Uncapped percent (0 when there is no allotment). */
  usedPct: number;
  /** Usage beyond the allotment, 0 when within it. */
  extra: number;
  /** True once usage is past the allotment. */
  over: boolean;
};

export function splitAllotment(used: number, allotted: number): AllotmentSplit {
  if (!(allotted > 0) || !Number.isFinite(used)) {
    return { fillPct: 0, usedPct: 0, extra: 0, over: false };
  }
  const usedPct = (Math.max(used, 0) / allotted) * 100;
  const extra = Math.max(used - allotted, 0);
  return { fillPct: Math.min(usedPct, 100), usedPct, extra, over: extra > 0 };
}

/** Neutral wording for the past-allotment state. */
export const INCLUDED_USAGE_COPY =
  "Included usage used. Additional usage is billed as extra cost.";

/** The one colour an allotment meter uses at every fill level. */
export const ALLOTMENT_BAR_COLOR = "var(--color-success)";
