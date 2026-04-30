"use client";

/**
 * Native terminal-styled <select> for org member role.
 * Uses ROLE_OPTIONS from lib/team/roles.ts — single source of truth.
 * Explicit focus-visible ring for dark-theme browser compat.
 */

import { ROLE_OPTIONS, type TeamRole } from "@/lib/team/roles";

export interface RoleSelectProps {
  value: TeamRole;
  onChange: (next: TeamRole) => void;
  disabled?: boolean;
  ariaLabel: string;
}

export function RoleSelect({ value, onChange, disabled = false, ariaLabel }: RoleSelectProps) {
  return (
    <select
      value={value}
      onChange={(e) => onChange(e.target.value as TeamRole)}
      disabled={disabled}
      aria-label={ariaLabel}
      className="px-2 py-1 bg-[var(--color-bg-input)] border border-[var(--color-border)] text-[12px] text-[var(--color-text)] font-mono tracking-wide disabled:opacity-40 cursor-pointer focus:outline-none focus-visible:ring-1 focus-visible:ring-[var(--color-text)] focus-visible:outline-none"
    >
      {ROLE_OPTIONS.map((opt) => (
        <option key={opt.value} value={opt.value}>
          {opt.label}
        </option>
      ))}
    </select>
  );
}
