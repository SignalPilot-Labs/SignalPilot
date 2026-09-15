/** Shared styles, types and formatters for the projects overview surfaces. */

export const OUTLINE_BUTTON =
  "inline-flex items-center justify-center gap-2 border border-[var(--color-border)] px-4 py-2 text-xs uppercase tracking-wider text-[var(--color-text-dim)] transition-all hover:border-[var(--color-text-dim)] hover:text-[var(--color-text)] disabled:cursor-not-allowed disabled:opacity-50";

export const PRIMARY_BUTTON =
  "inline-flex items-center justify-center gap-2 bg-[var(--color-text)] px-4 py-2 text-xs uppercase tracking-wider text-[var(--color-bg)] transition-all hover:opacity-90 disabled:cursor-not-allowed disabled:opacity-60";

export const ICON_BUTTON =
  "inline-flex h-8 w-8 items-center justify-center border border-transparent text-[var(--color-text-dim)] transition-colors hover:border-[var(--color-border)] hover:text-[var(--color-text)] disabled:cursor-not-allowed disabled:opacity-50";

export type NotionConversation = {
  id: string;
  title: string;
  source?: string;
  status?: string;
  notebook_path?: string;
  created_at?: number;
  updated_at?: number;
};

export function getErrorMessage(error: unknown): string {
  return error instanceof Error ? error.message : String(error);
}

export function slugifyProjectName(value: string): string {
  return value.trim().toLowerCase().replace(/[^a-z0-9_-]/g, "-");
}

export function formatBytes(value: number): string {
  if (!Number.isFinite(value) || value <= 0) {
    return "";
  }
  if (value < 1024) {
    return `${value} B`;
  }
  if (value < 1024 * 1024) {
    return `${Math.round(value / 1024)} KB`;
  }
  return `${(value / (1024 * 1024)).toFixed(1)} MB`;
}

export function formatRelativeTime(value?: number | null): string {
  if (!value) {
    return "";
  }
  const diffMs = Date.now() - value * 1000;
  const minute = 60 * 1000;
  const hour = 60 * minute;
  const day = 24 * hour;
  if (diffMs < minute) {
    return "just now";
  }
  if (diffMs < hour) {
    return `${Math.floor(diffMs / minute)}m ago`;
  }
  if (diffMs < day) {
    return `${Math.floor(diffMs / hour)}h ago`;
  }
  if (diffMs < 30 * day) {
    return `${Math.floor(diffMs / day)}d ago`;
  }
  return new Intl.DateTimeFormat(undefined, {
    month: "short",
    day: "numeric",
  }).format(new Date(value * 1000));
}

export function formatConversationTime(value?: number): string {
  if (!value) {
    return "";
  }
  return new Intl.DateTimeFormat(undefined, {
    month: "short",
    day: "numeric",
    hour: "2-digit",
    minute: "2-digit",
  }).format(new Date(value * 1000));
}
