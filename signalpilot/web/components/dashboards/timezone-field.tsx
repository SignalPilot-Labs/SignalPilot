"use client";

// The timezone control of a refresh schedule: a select of the browser zone
// and common IANA zones, with an "Other…" entry that swaps in a free-text
// input for anything else. Shared by the settings drawer and the publish
// dialog, along with the validation message both report.

import { useState } from "react";

import { isValidTimeZone, timezoneOptions } from "~/lib/dashboards/timezones";

const CUSTOM_OPTION = "__custom";

/** The problem with a zone, or null when `Intl` knows it. */
export function timeZoneProblem(zone: string): string | null {
  if (!zone.trim()) return "Pick a timezone for the schedule.";
  return isValidTimeZone(zone) ? null : `"${zone}" is not a known timezone.`;
}

export function TimezoneField({
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
  /** The select's test id; the free-text input is `${testId}-input`. */
  testId: string;
}) {
  const [custom, setCustom] = useState(false);

  if (custom) {
    return (
      <div className="space-y-1">
        <input
          id={id}
          data-testid={`${testId}-input`}
          value={value}
          disabled={disabled}
          onChange={(event) => onChange(event.target.value)}
          placeholder="Area/City"
          autoComplete="off"
          spellCheck={false}
          className={className}
        />
        <button
          type="button"
          data-testid={`${testId}-list`}
          disabled={disabled}
          onClick={() => setCustom(false)}
          className="text-[11px] text-[var(--color-text-dim)] underline-offset-2 hover:text-[var(--color-text)] hover:underline disabled:opacity-50"
        >
          Choose from the list
        </button>
      </div>
    );
  }

  return (
    <select
      id={id}
      data-testid={testId}
      value={value}
      disabled={disabled}
      onChange={(event) => {
        if (event.target.value === CUSTOM_OPTION) setCustom(true);
        else onChange(event.target.value);
      }}
      className={className}
    >
      {timezoneOptions(value).map((zone) => (
        <option key={zone} value={zone}>
          {zone}
        </option>
      ))}
      <option value={CUSTOM_OPTION}>Other (type an IANA zone)…</option>
    </select>
  );
}
