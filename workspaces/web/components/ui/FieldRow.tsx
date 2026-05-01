import React from "react";

export const DT_CLASS =
  "text-[11px] uppercase tracking-[0.15em] text-[var(--color-text-muted)] self-start pt-0.5";

export interface FieldRowProps {
  label: string;
  first?: boolean;
  children: React.ReactNode;
}

export function FieldRow({ label, first = false, children }: FieldRowProps): React.JSX.Element {
  return (
    <div
      className={`grid grid-cols-[140px_1fr] gap-4 py-2.5 text-[13px] ${
        first ? "" : "border-t border-[var(--color-border)]"
      }`}
    >
      <dt className={DT_CLASS}>{label}</dt>
      <dd>{children}</dd>
    </div>
  );
}
