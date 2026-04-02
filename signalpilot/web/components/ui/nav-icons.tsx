/* Custom SVG nav icons — geometric, minimal, brutalism-lite */

export function NavIconDashboard({ active }: { active: boolean }) {
  const s = active ? "currentColor" : "currentColor";
  return (
    <svg width="14" height="14" viewBox="0 0 14 14" fill="none">
      <rect x="1" y="1" width="5" height="5" stroke={s} strokeWidth="1" />
      <rect x="8" y="1" width="5" height="3" stroke={s} strokeWidth="1" />
      <rect x="8" y="6" width="5" height="7" stroke={s} strokeWidth="1" />
      <rect x="1" y="8" width="5" height="5" stroke={s} strokeWidth="1" />
    </svg>
  );
}

export function NavIconQuery({ active }: { active: boolean }) {
  return (
    <svg width="14" height="14" viewBox="0 0 14 14" fill="none">
      <path d="M2 3H12M2 7H8M2 11H10" stroke="currentColor" strokeWidth="1" strokeLinecap="square" />
      <path d="M10 8L12 10" stroke="currentColor" strokeWidth="1.5" strokeLinecap="square" />
      {active && <circle cx="11" cy="9" r="1" fill="var(--color-success)" />}
    </svg>
  );
}

export function NavIconSchema({ active }: { active: boolean }) {
  return (
    <svg width="14" height="14" viewBox="0 0 14 14" fill="none">
      <rect x="1" y="1" width="12" height="12" stroke="currentColor" strokeWidth="1" />
      <line x1="1" y1="5" x2="13" y2="5" stroke="currentColor" strokeWidth="0.75" />
      <line x1="5" y1="1" x2="5" y2="13" stroke="currentColor" strokeWidth="0.75" />
    </svg>
  );
}

export function NavIconSandbox({ active }: { active: boolean }) {
  return (
    <svg width="14" height="14" viewBox="0 0 14 14" fill="none">
      <rect x="1" y="1" width="12" height="12" stroke="currentColor" strokeWidth="1" />
      <path d="M4 5L6 7L4 9" stroke="currentColor" strokeWidth="1" strokeLinecap="square" />
      <line x1="7" y1="9" x2="10" y2="9" stroke="currentColor" strokeWidth="1" strokeLinecap="square" />
      {active && <rect x="10" y="2" width="2" height="2" fill="var(--color-success)" />}
    </svg>
  );
}

export function NavIconDatabase({ active }: { active: boolean }) {
  return (
    <svg width="14" height="14" viewBox="0 0 14 14" fill="none">
      <ellipse cx="7" cy="3" rx="5" ry="2" stroke="currentColor" strokeWidth="1" />
      <path d="M2 3V11C2 12.1 4.24 13 7 13C9.76 13 12 12.1 12 11V3" stroke="currentColor" strokeWidth="1" />
      <path d="M2 7C2 8.1 4.24 9 7 9C9.76 9 12 8.1 12 7" stroke="currentColor" strokeWidth="0.75" />
    </svg>
  );
}

export function NavIconHealth({ active }: { active: boolean }) {
  return (
    <svg width="14" height="14" viewBox="0 0 14 14" fill="none">
      <path d="M1 7H3L5 3L7 11L9 5L11 7H13" stroke="currentColor" strokeWidth="1" strokeLinecap="round" strokeLinejoin="round" />
      {active && <circle cx="7" cy="7" r="1" fill="var(--color-success)" />}
    </svg>
  );
}

export function NavIconAudit({ active }: { active: boolean }) {
  return (
    <svg width="14" height="14" viewBox="0 0 14 14" fill="none">
      <rect x="2" y="1" width="10" height="12" stroke="currentColor" strokeWidth="1" />
      <line x1="4" y1="4" x2="10" y2="4" stroke="currentColor" strokeWidth="0.75" />
      <line x1="4" y1="6.5" x2="10" y2="6.5" stroke="currentColor" strokeWidth="0.75" />
      <line x1="4" y1="9" x2="8" y2="9" stroke="currentColor" strokeWidth="0.75" />
    </svg>
  );
}

export function NavIconSettings({ active }: { active: boolean }) {
  return (
    <svg width="14" height="14" viewBox="0 0 14 14" fill="none">
      <circle cx="7" cy="7" r="2.5" stroke="currentColor" strokeWidth="1" />
      <path d="M7 1V3M7 11V13M1 7H3M11 7H13M2.5 2.5L4 4M10 10L11.5 11.5M11.5 2.5L10 4M4 10L2.5 11.5" stroke="currentColor" strokeWidth="0.75" strokeLinecap="square" />
    </svg>
  );
}

export type NavIconComponent = React.FC<{ active: boolean }>;
