"use client";

// Settings drawer for a published dashboard: identity, visibility and the
// refresh schedule. Submits one PATCH with the exact `refresh` shape the
// gateway expects; the schedule preview updates as the controls change.

import { X } from "lucide-react";
import { useEffect, useId, useRef, useState, type FormEvent } from "react";
import { createPortal } from "react-dom";

import {
  DASHBOARD_REFRESH_OPTIONS,
  type DashboardRefreshSettings,
  type DashboardVisibility,
  type PublishedDashboard,
  type UpdateDashboardRequest,
} from "~/lib/api/dashboards";
import { parseIntervalValue, refreshSummary } from "~/lib/dashboards/format";
import {
  DASHBOARD_REFRESH_MODE_OPTIONS,
  DASHBOARD_VISIBILITY_OPTIONS,
} from "~/lib/dashboards/options";
import { Switch } from "~/components/ui/switch";
import { useFocusTrap } from "~/components/ui/use-focus-trap";

import { AnchorTimeField, anchorTimeProblem } from "./anchor-time-field";
import { BUTTON_CLASS, PRIMARY_BUTTON_CLASS } from "./dashboard-chips";
import { TimezoneField, timeZoneProblem } from "./timezone-field";

const FIELD_CLASS =
  "h-9 w-full rounded-[10px] border border-[var(--color-border)] bg-[var(--color-bg-input)] px-3 text-[12.5px] text-[var(--color-text)] outline-none transition-colors placeholder:text-[var(--color-text-dim)] focus:border-[var(--color-border-active)]";
const LABEL_CLASS = "mb-1.5 block text-[11px] uppercase tracking-[0.08em] text-[var(--color-text-dim)]";
const HELP_CLASS = "mt-1 text-[11.5px] leading-4 text-[var(--color-text-dim)]";

export type DashboardSettingsDraft = {
  name: string;
  description: string;
  visibility: DashboardVisibility;
  refresh: DashboardRefreshSettings;
  notify_on_failure: boolean;
};

export function draftFromDashboard(dashboard: PublishedDashboard): DashboardSettingsDraft {
  return {
    name: dashboard.name,
    description: dashboard.description ?? "",
    visibility: dashboard.visibility,
    refresh: {
      interval_minutes: dashboard.refresh.interval_minutes,
      anchor_time: dashboard.refresh.anchor_time ?? "06:00",
      timezone: dashboard.refresh.timezone || "UTC",
      mode: dashboard.refresh.mode,
    },
    notify_on_failure: dashboard.notify_on_failure,
  };
}

export function requestFromDraft(draft: DashboardSettingsDraft): UpdateDashboardRequest {
  return {
    name: draft.name.trim(),
    description: draft.description.trim() ? draft.description.trim() : null,
    visibility: draft.visibility,
    refresh: {
      interval_minutes: draft.refresh.interval_minutes,
      anchor_time: draft.refresh.anchor_time ?? "06:00",
      timezone: draft.refresh.timezone,
      mode: draft.refresh.mode,
    },
    notify_on_failure: draft.notify_on_failure,
  };
}

export function validateDraft(draft: DashboardSettingsDraft): string | null {
  if (!draft.name.trim()) return "Give the dashboard a name.";
  return anchorTimeProblem(draft.refresh.anchor_time ?? "") ?? timeZoneProblem(draft.refresh.timezone);
}

export function DashboardSettingsDrawer({
  open,
  dashboard,
  onClose,
  onSubmit,
}: {
  open: boolean;
  dashboard: PublishedDashboard;
  onClose: () => void;
  onSubmit: (body: UpdateDashboardRequest) => Promise<void>;
}) {
  const [draft, setDraft] = useState<DashboardSettingsDraft>(() => draftFromDashboard(dashboard));
  const [error, setError] = useState<string | null>(null);
  const [saving, setSaving] = useState(false);
  const panelRef = useRef<HTMLDivElement>(null);
  const ids = useId();
  useFocusTrap(panelRef, open);

  // Re-seed the form each time the drawer opens on the latest server state.
  useEffect(() => {
    if (!open) return;
    setDraft(draftFromDashboard(dashboard));
    setError(null);
  }, [open, dashboard]);

  useEffect(() => {
    if (!open) return;
    const onKey = (event: KeyboardEvent) => {
      if (event.key === "Escape") onClose();
    };
    document.addEventListener("keydown", onKey);
    return () => document.removeEventListener("keydown", onKey);
  }, [open, onClose]);

  // Portal to the body: the page transition wrapper is transformed, which
  // would otherwise turn `fixed` into a scrolling overlay inside the page.
  if (!open || typeof document === "undefined") return null;

  const patchRefresh = (patch: Partial<DashboardRefreshSettings>) =>
    setDraft((prev) => ({ ...prev, refresh: { ...prev.refresh, ...patch } }));

  const submit = async (event: FormEvent) => {
    event.preventDefault();
    const problem = validateDraft(draft);
    if (problem) {
      setError(problem);
      return;
    }
    setSaving(true);
    setError(null);
    try {
      await onSubmit(requestFromDraft(draft));
      onClose();
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : "Could not save the settings.");
    } finally {
      setSaving(false);
    }
  };

  const preview = refreshSummary(draft.refresh);

  return createPortal(
    <div className="fixed inset-0 z-[80] flex justify-end bg-black/60" onClick={onClose}>
      <div
        ref={panelRef}
        role="dialog"
        aria-modal="true"
        aria-labelledby={`${ids}-title`}
        data-testid="dashboard-settings-drawer"
        onClick={(event) => event.stopPropagation()}
        className="flex h-full w-full max-w-[440px] flex-col border-l border-[var(--color-border)] bg-[var(--color-bg-card)] shadow-2xl animate-slide-in-right"
      >
        <div className="flex items-center justify-between border-b border-[var(--color-border)] px-5 py-3.5">
          <h2 id={`${ids}-title`} className="text-[14px] font-semibold text-[var(--color-text)]">
            Dashboard settings
          </h2>
          <button type="button" aria-label="Close settings" onClick={onClose} className={BUTTON_CLASS}>
            <X className="h-3.5 w-3.5" />
          </button>
        </div>
        <form onSubmit={submit} className="flex min-h-0 flex-1 flex-col">
          <div className="flex-1 space-y-5 overflow-y-auto px-5 py-5">
            <div>
              <label htmlFor={`${ids}-name`} className={LABEL_CLASS}>Name</label>
              <input
                id={`${ids}-name`}
                value={draft.name}
                onChange={(event) => setDraft((prev) => ({ ...prev, name: event.target.value }))}
                className={FIELD_CLASS}
                maxLength={200}
              />
            </div>
            <div>
              <label htmlFor={`${ids}-description`} className={LABEL_CLASS}>Description</label>
              <textarea
                id={`${ids}-description`}
                value={draft.description}
                onChange={(event) => setDraft((prev) => ({ ...prev, description: event.target.value }))}
                rows={3}
                className={`${FIELD_CLASS} h-auto resize-y py-2 leading-5`}
              />
            </div>
            <div>
              <label htmlFor={`${ids}-visibility`} className={LABEL_CLASS}>Visibility</label>
              <select
                id={`${ids}-visibility`}
                value={draft.visibility}
                onChange={(event) => setDraft((prev) => ({ ...prev, visibility: event.target.value as DashboardVisibility }))}
                className={FIELD_CLASS}
              >
                {DASHBOARD_VISIBILITY_OPTIONS.map((option) => (
                  <option key={option.value} value={option.value}>{option.label}</option>
                ))}
              </select>
              <p className={HELP_CLASS}>{DASHBOARD_VISIBILITY_OPTIONS.find((o) => o.value === draft.visibility)?.hint}</p>
            </div>

            <fieldset className="rounded-xl border border-[var(--color-border)] p-4">
              <legend className="px-1 text-[11px] uppercase tracking-[0.08em] text-[var(--color-text-dim)]">
                Refresh
              </legend>
              <div className="space-y-4">
                <div>
                  <label htmlFor={`${ids}-interval`} className={LABEL_CLASS}>Interval</label>
                  <select
                    id={`${ids}-interval`}
                    data-testid="dashboard-settings-interval"
                    value={draft.refresh.interval_minutes ?? ""}
                    onChange={(event) => patchRefresh({ interval_minutes: parseIntervalValue(event.target.value) })}
                    className={FIELD_CLASS}
                  >
                    {DASHBOARD_REFRESH_OPTIONS.map((option) => (
                      <option key={option.label} value={option.value ?? ""}>{option.label}</option>
                    ))}
                  </select>
                </div>
                <div className="grid grid-cols-[120px_minmax(0,1fr)] gap-3">
                  <div>
                    <label htmlFor={`${ids}-anchor`} className={LABEL_CLASS}>Aligned to</label>
                    <AnchorTimeField
                      id={`${ids}-anchor`}
                      testId="dashboard-settings-anchor"
                      value={draft.refresh.anchor_time ?? ""}
                      onChange={(anchor_time) => patchRefresh({ anchor_time })}
                      className={FIELD_CLASS}
                    />
                  </div>
                  <div>
                    <label htmlFor={`${ids}-zone`} className={LABEL_CLASS}>Timezone</label>
                    <TimezoneField
                      id={`${ids}-zone`}
                      testId="dashboard-settings-timezone"
                      value={draft.refresh.timezone}
                      onChange={(timezone) => patchRefresh({ timezone })}
                      className={FIELD_CLASS}
                    />
                  </div>
                </div>
                <p className={HELP_CLASS}>
                  Runs align to this wall-clock time: daily at it, sub-daily intervals stepping from it.
                </p>
                <div>
                  <span className={LABEL_CLASS}>Mode</span>
                  <div role="radiogroup" aria-label="Refresh mode" className="space-y-2">
                    {DASHBOARD_REFRESH_MODE_OPTIONS.map((option) => (
                      <label
                        key={option.value}
                        className={`flex cursor-pointer items-start gap-2.5 rounded-[10px] border px-3 py-2 transition-colors ${
                          draft.refresh.mode === option.value
                            ? "border-[var(--color-border-active)] bg-[var(--color-bg-hover)]"
                            : "border-[var(--color-border)] hover:border-[var(--color-border-hover)]"
                        }`}
                      >
                        <input
                          type="radio"
                          name={`${ids}-mode`}
                          value={option.value}
                          checked={draft.refresh.mode === option.value}
                          onChange={() => patchRefresh({ mode: option.value })}
                          className="mt-0.5 accent-[var(--color-text)]"
                        />
                        <span>
                          <span className="block text-[12.5px] text-[var(--color-text)]">{option.label}</span>
                          <span className="block text-[11.5px] leading-4 text-[var(--color-text-dim)]">{option.hint}</span>
                        </span>
                      </label>
                    ))}
                  </div>
                </div>
                <div className="flex items-center justify-between gap-4">
                  <span id={`${ids}-notify`} className="text-[12.5px] text-[var(--color-text)]">
                    Notify on failure
                  </span>
                  <Switch
                    size="sm"
                    checked={draft.notify_on_failure}
                    onCheckedChange={(checked) => setDraft((prev) => ({ ...prev, notify_on_failure: checked }))}
                    aria-labelledby={`${ids}-notify`}
                    data-testid="dashboard-settings-notify"
                  />
                </div>
              </div>
            </fieldset>
          </div>
          <div className="flex items-center gap-3 border-t border-[var(--color-border)] px-5 py-3.5">
            <p
              data-testid="dashboard-settings-preview"
              className="flex-1 truncate text-[12px] text-[var(--color-text-muted)]"
              title={preview}
            >
              Schedule: <span className="text-[var(--color-text)]">{preview}</span>
            </p>
            {error && (
              <p role="alert" className="text-[11.5px] text-[var(--color-error)]">{error}</p>
            )}
            <button type="button" onClick={onClose} className={BUTTON_CLASS}>Cancel</button>
            <button type="submit" disabled={saving} data-testid="dashboard-settings-save" className={PRIMARY_BUTTON_CLASS}>
              {saving ? "Saving…" : "Save"}
            </button>
          </div>
        </form>
      </div>
    </div>,
    document.body,
  );
}
