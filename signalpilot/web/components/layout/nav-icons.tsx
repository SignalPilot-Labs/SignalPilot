/* Custom SVG nav icons — geometric, minimal, brutalism-lite.
   Each icon takes `active` and lights a success-colored accent when set. */

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
export function NavIconLineage({ active }: { active: boolean }) {
  return (
    <svg width="14" height="14" viewBox="0 0 14 14" fill="none">
      <rect x="1" y="5.5" width="3" height="3" stroke="currentColor" strokeWidth="1" />
      <rect x="10" y="1.5" width="3" height="3" stroke="currentColor" strokeWidth="1" />
      <rect x="10" y="9.5" width="3" height="3" stroke="currentColor" strokeWidth="1" />
      <path d="M4 7H6.5C7.5 7 7.5 3 8.5 3H10M4 7H6.5C7.5 7 7.5 11 8.5 11H10" stroke="currentColor" strokeWidth="1" fill="none" />
      {active && <rect x="1.75" y="6.25" width="1.5" height="1.5" fill="var(--color-success)" />}
    </svg>
  );
}
export function NavIconIntegrations({ active }: { active: boolean }) {
  return (
    <svg width="14" height="14" viewBox="0 0 14 14" fill="none">
      <circle cx="4" cy="4" r="2.5" stroke="currentColor" strokeWidth="1" />
      <circle cx="10" cy="10" r="2.5" stroke="currentColor" strokeWidth="1" />
      <path d="M6 5.5L8 8.5" stroke="currentColor" strokeWidth="1" strokeLinecap="round" />
      {active && <circle cx="7" cy="7" r="1" fill="var(--color-success)" />}
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
export function NavIconProject({ active }: { active: boolean }) {
  return (
    <svg width="14" height="14" viewBox="0 0 14 14" fill="none">
      <path d="M1 3L1 12H13V3H7L5 1H1V3Z" stroke="currentColor" strokeWidth="1" strokeLinejoin="miter" fill="none" />
      {active && <rect x="5" y="6" width="4" height="3" fill="var(--color-success)" />}
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
export function NavIconKnowledge({ active }: { active: boolean }) {
  return (
    <svg width="14" height="14" viewBox="0 0 14 14" fill="none">
      <rect x="1" y="3" width="10" height="10" stroke="currentColor" strokeWidth="1" />
      <rect x="3" y="1" width="10" height="10" stroke="currentColor" strokeWidth="1" />
      <line x1="5" y1="5" x2="11" y2="5" stroke="currentColor" strokeWidth="0.75" />
      <line x1="5" y1="7.5" x2="11" y2="7.5" stroke="currentColor" strokeWidth="0.75" />
      <line x1="5" y1="10" x2="9" y2="10" stroke="currentColor" strokeWidth="0.75" />
      {active && <rect x="10" y="2" width="2" height="2" fill="var(--color-success)" />}
    </svg>
  );
}

export function NavIconReports({ active }: { active: boolean }) {
  return (
    <svg width="14" height="14" viewBox="0 0 14 14" fill="none">
      <path d="M3 1h5l3 3v9H3z" stroke="currentColor" strokeWidth="1" />
      <path d="M8 1v3h3" stroke="currentColor" strokeWidth="1" />
      <line x1="5" y1="8" x2="9" y2="8" stroke="currentColor" strokeWidth="0.75" />
      <line x1="5" y1="10.5" x2="8.5" y2="10.5" stroke="currentColor" strokeWidth="0.75" />
      {active && <rect x="9.5" y="9.5" width="2" height="2" fill="var(--color-success)" />}
    </svg>
  );
}

export function NavIconEvals({ active }: { active: boolean }) {
  return (
    <svg width="14" height="14" viewBox="0 0 14 14" fill="none">
      <path d="M5 1H9M6 1V5L2.5 11.5C2 12.4 2.6 13 3.4 13H10.6C11.4 13 12 12.4 11.5 11.5L8 5V1" stroke="currentColor" strokeWidth="1" strokeLinejoin="round" />
      <line x1="4" y1="9.5" x2="10" y2="9.5" stroke="currentColor" strokeWidth="0.75" />
      {active && <circle cx="7" cy="11" r="1" fill="var(--color-success)" />}
    </svg>
  );
}

export function NavIconAccuracy({ active }: { active: boolean }) {
  return (
    <svg width="14" height="14" viewBox="0 0 14 14" fill="none">
      <path d="M2 11V8M5.3 11V5M8.7 11V7M12 11V2" stroke="currentColor" strokeWidth="1" />
      <path d="M1 12.5H13" stroke="currentColor" strokeWidth="1" />
      {active && <circle cx="12" cy="2" r="1.25" fill="var(--color-success)" />}
    </svg>
  );
}

export function NavIconChats({ active }: { active: boolean }) {
  return (
    <svg width="14" height="14" viewBox="0 0 14 14" fill="none">
      <path d="M1 2h12v8H5l-3 3v-3H1z" stroke="currentColor" strokeWidth="1" />
      <line x1="3.5" y1="5" x2="10.5" y2="5" stroke="currentColor" strokeWidth="0.75" />
      <line x1="3.5" y1="7.5" x2="8.5" y2="7.5" stroke="currentColor" strokeWidth="0.75" />
      {active && <rect x="10" y="7" width="2" height="2" fill="var(--color-success)" />}
    </svg>
  );
}

export function NavIconGitHub({ active }: { active: boolean }) {
  return (
    <svg width="14" height="14" viewBox="0 0 14 14" fill="none">
      <path d="M7 1C3.7 1 1 3.7 1 7c0 2.7 1.7 4.9 4.1 5.7.3.1.4-.1.4-.3v-1c-1.7.4-2-.8-2-.8-.3-.7-.7-.9-.7-.9-.5-.4 0-.4 0-.4.6 0 .9.6.9.6.5.9 1.4.6 1.7.5.1-.4.2-.6.4-.8-1.3-.1-2.7-.7-2.7-3 0-.7.2-1.2.6-1.7-.1-.1-.3-.8.1-1.6 0 0 .5-.2 1.7.6.5-.1 1-.2 1.5-.2s1 .1 1.5.2c1.2-.8 1.7-.6 1.7-.6.3.8.1 1.5.1 1.6.4.4.6 1 .6 1.7 0 2.3-1.4 2.8-2.7 3 .2.2.4.5.4 1.1v1.6c0 .2.1.4.4.3C11.3 11.9 13 9.7 13 7c0-3.3-2.7-6-6-6z" stroke="currentColor" strokeWidth="0.5" fill={active ? "currentColor" : "none"} />
    </svg>
  );
}
