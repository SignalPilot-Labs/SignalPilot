"use client";

// The "Aligned to" control of a refresh schedule: one `type="time"` input
// producing the "HH:MM" the gateway stores, plus the validation both forms
// (settings drawer, publish dialog) report with the same words.

import { isValidAnchorTime } from "~/lib/dashboards/format";

const ANCHOR_TIME_PROBLEM = "Aligned to must be a 24 h time like 06:00.";

/** The problem with an anchor time, or null when it is a valid "HH:MM". */
export function anchorTimeProblem(value: string): string | null {
  return isValidAnchorTime(value) ? null : ANCHOR_TIME_PROBLEM;
}

export function AnchorTimeField({
  id,
  value,
  onChange,
  disabled = false,
  className,
  testId,
}: {
  id: string;
  value: string;
  onChange: (value: string) => void;
  disabled?: boolean;
  /** The host form's input styling. */
  className: string;
  testId: string;
}) {
  return (
    <input
      id={id}
      data-testid={testId}
      type="time"
      value={value}
      disabled={disabled}
      onChange={(event) => onChange(event.target.value)}
      className={`${className} font-mono`}
    />
  );
}
