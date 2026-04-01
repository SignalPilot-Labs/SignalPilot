"use client";

import type { ToolCategory } from "@/lib/types";

// Each tool type gets a unique hand-drawn SVG icon
// All icons: 14x14 viewBox, stroke-only, strokeWidth 1.5, currentColor

export function BashIcon({ color }: { color?: string }) {
  return (
    <svg width="14" height="14" viewBox="0 0 14 14" fill="none" stroke={color || "currentColor"} strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round">
      <polyline points="2 4 5 7 2 10" />
      <line x1="7" y1="10" x2="12" y2="10" />
    </svg>
  );
}

export function ReadIcon({ color }: { color?: string }) {
  return (
    <svg width="14" height="14" viewBox="0 0 14 14" fill="none" stroke={color || "currentColor"} strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round">
      <path d="M3 2h6l3 3v7a1 1 0 01-1 1H3a1 1 0 01-1-1V3a1 1 0 011-1z" />
      <polyline points="9 2 9 5 12 5" />
      <line x1="4" y1="8" x2="10" y2="8" />
      <line x1="4" y1="10" x2="8" y2="10" />
    </svg>
  );
}

export function WriteIcon({ color }: { color?: string }) {
  return (
    <svg width="14" height="14" viewBox="0 0 14 14" fill="none" stroke={color || "currentColor"} strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round">
      <path d="M3 2h6l3 3v7a1 1 0 01-1 1H3a1 1 0 01-1-1V3a1 1 0 011-1z" />
      <polyline points="9 2 9 5 12 5" />
      <line x1="5" y1="7" x2="5" y2="11" />
      <line x1="3" y1="9" x2="7" y2="9" />
    </svg>
  );
}

export function EditIcon({ color }: { color?: string }) {
  return (
    <svg width="14" height="14" viewBox="0 0 14 14" fill="none" stroke={color || "currentColor"} strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round">
      <path d="M9.5 1.5l3 3L5 12H2v-3L9.5 1.5z" />
      <line x1="8" y1="3" x2="11" y2="6" />
    </svg>
  );
}

export function GlobIcon({ color }: { color?: string }) {
  return (
    <svg width="14" height="14" viewBox="0 0 14 14" fill="none" stroke={color || "currentColor"} strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round">
      <path d="M2 3h3l1 1h5a1 1 0 011 1v6a1 1 0 01-1 1H3a1 1 0 01-1-1V3z" />
      <path d="M6 8l1.5-1.5L9 8" />
      <line x1="7.5" y1="6.5" x2="7.5" y2="10" />
    </svg>
  );
}

export function GrepIcon({ color }: { color?: string }) {
  return (
    <svg width="14" height="14" viewBox="0 0 14 14" fill="none" stroke={color || "currentColor"} strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round">
      <circle cx="6" cy="6" r="4" />
      <line x1="9" y1="9" x2="12.5" y2="12.5" />
      <line x1="4" y1="6" x2="8" y2="6" />
    </svg>
  );
}

export function AgentIcon({ color }: { color?: string }) {
  return (
    <svg width="14" height="14" viewBox="0 0 14 14" fill="none" stroke={color || "currentColor"} strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round">
      <circle cx="7" cy="4" r="2.5" />
      <path d="M3 12c0-2.2 1.8-4 4-4s4 1.8 4 4" />
      <circle cx="11" cy="3" r="1.5" strokeDasharray="2 1.5" />
    </svg>
  );
}

export function WebSearchIcon({ color }: { color?: string }) {
  return (
    <svg width="14" height="14" viewBox="0 0 14 14" fill="none" stroke={color || "currentColor"} strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round">
      <circle cx="7" cy="7" r="5.5" />
      <ellipse cx="7" cy="7" rx="2.5" ry="5.5" />
      <line x1="1.5" y1="7" x2="12.5" y2="7" />
    </svg>
  );
}

export function WebFetchIcon({ color }: { color?: string }) {
  return (
    <svg width="14" height="14" viewBox="0 0 14 14" fill="none" stroke={color || "currentColor"} strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round">
      <path d="M1.5 3h11v8a1 1 0 01-1 1h-9a1 1 0 01-1-1V3z" />
      <line x1="1.5" y1="5.5" x2="12.5" y2="5.5" />
      <circle cx="3" cy="4.2" r="0.4" fill={color || "currentColor"} stroke="none" />
      <circle cx="4.5" cy="4.2" r="0.4" fill={color || "currentColor"} stroke="none" />
      <circle cx="6" cy="4.2" r="0.4" fill={color || "currentColor"} stroke="none" />
      <line x1="5" y1="8" x2="9" y2="8" />
      <line x1="4" y1="10" x2="10" y2="10" />
    </svg>
  );
}

export function TodoIcon({ color }: { color?: string }) {
  return (
    <svg width="14" height="14" viewBox="0 0 14 14" fill="none" stroke={color || "currentColor"} strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round">
      <rect x="2" y="1.5" width="10" height="11" rx="1" />
      <polyline points="4.5 5 5.5 6 7.5 4" />
      <line x1="9" y1="5" x2="10.5" y2="5" />
      <line x1="4.5" y1="8" x2="10.5" y2="8" />
      <line x1="4.5" y1="10.5" x2="8" y2="10.5" />
    </svg>
  );
}

export function ToolSearchIcon({ color }: { color?: string }) {
  return (
    <svg width="14" height="14" viewBox="0 0 14 14" fill="none" stroke={color || "currentColor"} strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round">
      <rect x="1.5" y="2" width="7" height="10" rx="1" />
      <line x1="3.5" y1="5" x2="6.5" y2="5" />
      <line x1="3.5" y1="7" x2="6.5" y2="7" />
      <line x1="3.5" y1="9" x2="5.5" y2="9" />
      <circle cx="10.5" cy="9.5" r="2" />
      <line x1="12" y1="11" x2="13" y2="12" />
    </svg>
  );
}

export function SkillIcon({ color }: { color?: string }) {
  return (
    <svg width="14" height="14" viewBox="0 0 14 14" fill="none" stroke={color || "currentColor"} strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round">
      <polygon points="7 1 8.5 5 13 5 9.5 8 10.5 12 7 9.5 3.5 12 4.5 8 1 5 5.5 5" />
    </svg>
  );
}

export function PlaywrightNavigateIcon({ color }: { color?: string }) {
  return (
    <svg width="14" height="14" viewBox="0 0 14 14" fill="none" stroke={color || "currentColor"} strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round">
      <rect x="1" y="2" width="12" height="10" rx="1.5" />
      <line x1="1" y1="5" x2="13" y2="5" />
      <circle cx="2.8" cy="3.5" r="0.5" fill={color || "currentColor"} stroke="none" />
      <circle cx="4.5" cy="3.5" r="0.5" fill={color || "currentColor"} stroke="none" />
      <circle cx="6.2" cy="3.5" r="0.5" fill={color || "currentColor"} stroke="none" />
      <path d="M5 9l2-2 2 2" />
    </svg>
  );
}

export function PlaywrightScreenshotIcon({ color }: { color?: string }) {
  return (
    <svg width="14" height="14" viewBox="0 0 14 14" fill="none" stroke={color || "currentColor"} strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round">
      <rect x="2" y="3" width="10" height="8" rx="1" />
      <circle cx="7" cy="7" r="2" />
      <path d="M5 3V2h4v1" />
    </svg>
  );
}

export function PlaywrightSnapshotIcon({ color }: { color?: string }) {
  return (
    <svg width="14" height="14" viewBox="0 0 14 14" fill="none" stroke={color || "currentColor"} strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round">
      <rect x="2" y="2" width="10" height="10" rx="1" />
      <path d="M2 2l10 10M12 2L2 12" opacity="0.3" />
      <rect x="4.5" y="4.5" width="5" height="5" rx="0.5" />
    </svg>
  );
}

export function PlaywrightClickIcon({ color }: { color?: string }) {
  return (
    <svg width="14" height="14" viewBox="0 0 14 14" fill="none" stroke={color || "currentColor"} strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round">
      <path d="M4 1v7.5l2-2 1.5 3.5 1.5-.5-1.5-3.5H10L4 1z" />
    </svg>
  );
}

export function PlaywrightFormIcon({ color }: { color?: string }) {
  return (
    <svg width="14" height="14" viewBox="0 0 14 14" fill="none" stroke={color || "currentColor"} strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round">
      <rect x="2" y="3" width="10" height="3" rx="0.5" />
      <rect x="2" y="8" width="10" height="3" rx="0.5" />
      <line x1="4" y1="4.5" x2="4" y2="4.5" strokeWidth="2" />
      <line x1="4" y1="9.5" x2="7" y2="9.5" />
    </svg>
  );
}

export function PlaywrightEvaluateIcon({ color }: { color?: string }) {
  return (
    <svg width="14" height="14" viewBox="0 0 14 14" fill="none" stroke={color || "currentColor"} strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round">
      <polyline points="3 4 6 7 3 10" />
      <line x1="7" y1="10" x2="11" y2="10" />
      <path d="M1 1h12v12H1z" strokeDasharray="2 2" opacity="0.3" />
    </svg>
  );
}

export function SessionGateIcon({ color }: { color?: string }) {
  return (
    <svg width="14" height="14" viewBox="0 0 14 14" fill="none" stroke={color || "currentColor"} strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round">
      <rect x="3" y="6" width="8" height="6" rx="1" />
      <path d="M5 6V4a2 2 0 014 0v2" />
      <circle cx="7" cy="9.5" r="1" />
    </svg>
  );
}

export function DefaultToolIcon({ color }: { color?: string }) {
  return (
    <svg width="14" height="14" viewBox="0 0 14 14" fill="none" stroke={color || "currentColor"} strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round">
      <path d="M8.5 2L12 5.5 5.5 12H2V8.5L8.5 2z" />
      <path d="M9.5 5.5l-2-2" />
    </svg>
  );
}

// Audit event type icons
export function RoundCompleteIcon({ color }: { color?: string }) {
  return (
    <svg width="14" height="14" viewBox="0 0 14 14" fill="none" stroke={color || "currentColor"} strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round">
      <circle cx="7" cy="7" r="5.5" />
      <polyline points="4.5 7 6.5 9 9.5 5" />
    </svg>
  );
}

export function RunStartedIcon({ color }: { color?: string }) {
  return (
    <svg width="14" height="14" viewBox="0 0 14 14" fill="none" stroke={color || "currentColor"} strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round">
      <polygon points="4 2 12 7 4 12" />
    </svg>
  );
}

export function PRCreatedIcon({ color }: { color?: string }) {
  return (
    <svg width="14" height="14" viewBox="0 0 14 14" fill="none" stroke={color || "currentColor"} strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round">
      <circle cx="4" cy="4" r="1.5" />
      <circle cx="10" cy="4" r="1.5" />
      <circle cx="4" cy="10" r="1.5" />
      <line x1="4" y1="5.5" x2="4" y2="8.5" />
      <path d="M10 5.5c0 2-2 3-6 4.5" />
    </svg>
  );
}

export function ErrorIcon({ color }: { color?: string }) {
  return (
    <svg width="14" height="14" viewBox="0 0 14 14" fill="none" stroke={color || "currentColor"} strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round">
      <path d="M6.1 1.5L0.5 12h13L7.9 1.5a1 1 0 00-1.8 0z" />
      <line x1="7" y1="5.5" x2="7" y2="8.5" />
      <circle cx="7" cy="10" r="0.5" fill={color || "currentColor"} stroke="none" />
    </svg>
  );
}

export function KilledIcon({ color }: { color?: string }) {
  return (
    <svg width="14" height="14" viewBox="0 0 14 14" fill="none" stroke={color || "currentColor"} strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round">
      <circle cx="7" cy="7" r="5.5" />
      <line x1="4.5" y1="4.5" x2="9.5" y2="9.5" />
      <line x1="9.5" y1="4.5" x2="4.5" y2="9.5" />
    </svg>
  );
}

export function SessionEndedIcon({ color }: { color?: string }) {
  return (
    <svg width="14" height="14" viewBox="0 0 14 14" fill="none" stroke={color || "currentColor"} strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round">
      <rect x="2" y="2" width="10" height="10" rx="2" />
      <line x1="5" y1="5" x2="9" y2="9" />
      <line x1="9" y1="5" x2="5" y2="9" />
    </svg>
  );
}

export function CEOIcon({ color }: { color?: string }) {
  return (
    <svg width="14" height="14" viewBox="0 0 14 14" fill="none" stroke={color || "currentColor"} strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round">
      <path d="M2 10l2.5-5 2.5 3 2.5-4 2.5 6" />
      <rect x="1" y="10" width="12" height="2" rx="0.5" />
    </svg>
  );
}

export function WorkerAssignmentIcon({ color }: { color?: string }) {
  return (
    <svg width="14" height="14" viewBox="0 0 14 14" fill="none" stroke={color || "currentColor"} strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round">
      <rect x="2" y="2" width="10" height="10" rx="1" />
      <line x1="5" y1="5" x2="9" y2="5" />
      <line x1="5" y1="7" x2="9" y2="7" />
      <line x1="5" y1="9" x2="7" y2="9" />
      <path d="M2 2l1.5 1.5M12 2l-1.5 1.5" opacity="0.4" />
    </svg>
  );
}

export function RateLimitIcon({ color }: { color?: string }) {
  return (
    <svg width="14" height="14" viewBox="0 0 14 14" fill="none" stroke={color || "currentColor"} strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round">
      <circle cx="7" cy="7" r="5.5" />
      <line x1="7" y1="3.5" x2="7" y2="7" />
      <line x1="7" y1="7" x2="9.5" y2="9" />
    </svg>
  );
}

export function ConfigIcon({ color }: { color?: string }) {
  return (
    <svg width="14" height="14" viewBox="0 0 14 14" fill="none" stroke={color || "currentColor"} strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round">
      <circle cx="7" cy="7" r="2" />
      <path d="M7 1v2M7 11v2M1 7h2M11 7h2M2.8 2.8l1.4 1.4M9.8 9.8l1.4 1.4M2.8 11.2l1.4-1.4M9.8 4.2l1.4-1.4" />
    </svg>
  );
}

export function UnlockIcon({ color }: { color?: string }) {
  return (
    <svg width="14" height="14" viewBox="0 0 14 14" fill="none" stroke={color || "currentColor"} strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round">
      <rect x="3" y="6" width="8" height="6" rx="1" />
      <path d="M5 6V4a2 2 0 014 0" />
      <circle cx="7" cy="9.5" r="1" />
    </svg>
  );
}

export function StopRequestIcon({ color }: { color?: string }) {
  return (
    <svg width="14" height="14" viewBox="0 0 14 14" fill="none" stroke={color || "currentColor"} strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round">
      <rect x="3" y="3" width="8" height="8" rx="1" />
    </svg>
  );
}

// Map tool category to icon component
export function getToolIcon(category: ToolCategory, color?: string) {
  switch (category) {
    case "bash": return <BashIcon color={color} />;
    case "read": return <ReadIcon color={color} />;
    case "write": return <WriteIcon color={color} />;
    case "edit": return <EditIcon color={color} />;
    case "glob": return <GlobIcon color={color} />;
    case "grep": return <GrepIcon color={color} />;
    case "agent": return <AgentIcon color={color} />;
    case "web_search": return <WebSearchIcon color={color} />;
    case "web_fetch": return <WebFetchIcon color={color} />;
    case "todo": return <TodoIcon color={color} />;
    case "tool_search": return <ToolSearchIcon color={color} />;
    case "skill": return <SkillIcon color={color} />;
    case "playwright_navigate": return <PlaywrightNavigateIcon color={color} />;
    case "playwright_screenshot": return <PlaywrightScreenshotIcon color={color} />;
    case "playwright_snapshot": return <PlaywrightSnapshotIcon color={color} />;
    case "playwright_click": return <PlaywrightClickIcon color={color} />;
    case "playwright_form": case "playwright_type": return <PlaywrightFormIcon color={color} />;
    case "playwright_evaluate": return <PlaywrightEvaluateIcon color={color} />;
    case "session_gate": return <SessionGateIcon color={color} />;
    default: return <DefaultToolIcon color={color} />;
  }
}

// Map audit event type to icon
export function getAuditIcon(eventType: string, color?: string) {
  switch (eventType) {
    case "round_complete": return <RoundCompleteIcon color={color} />;
    case "run_started": return <RunStartedIcon color={color} />;
    case "pr_created": return <PRCreatedIcon color={color} />;
    case "pr_failed": return <ErrorIcon color={color} />;
    case "fatal_error": return <ErrorIcon color={color} />;
    case "killed": return <KilledIcon color={color} />;
    case "session_ended": return <SessionEndedIcon color={color} />;
    case "agent_stop": return <StopRequestIcon color={color} />;
    case "ceo_continuation": return <CEOIcon color={color} />;
    case "worker_assignment": return <WorkerAssignmentIcon color={color} />;
    case "rate_limit": case "rate_limit_paused": return <RateLimitIcon color={color} />;
    case "sdk_config": return <ConfigIcon color={color} />;
    case "session_unlocked": return <UnlockIcon color={color} />;
    case "end_session_denied": return <SessionGateIcon color={color} />;
    case "stop_requested": return <StopRequestIcon color={color} />;
    default: return <DefaultToolIcon color={color} />;
  }
}
