"use client";

// Publish a chat dashboard artifact to the team gallery. The dialog owns
// the form (see dashboard-publish-form.ts for the model), validates the
// dataset files against the conversation manifest before it lets the user
// submit, and reports gateway failures inline where the fix is.

import { AlertCircle, CheckCircle2, ExternalLink, Loader2, Upload, X } from "lucide-react";
import Link from "next/link";
import {
  useCallback,
  useContext,
  useEffect,
  useId,
  useMemo,
  useRef,
  useState,
  type ReactNode,
} from "react";
import { createPortal } from "react-dom";
import type { ConversationFileInfo } from "~/lib/api";
import {
  DASHBOARD_REFRESH_OPTIONS,
  type DashboardRefreshInterval,
  type PublishedDashboard,
} from "~/lib/api/dashboards";
import type { DashboardSpec } from "~/dashboard-renderer";
import { useFocusTrap } from "~/components/ui/use-focus-trap";
import {
  DASHBOARD_REFRESH_MODE_OPTIONS,
  DASHBOARD_VISIBILITY_OPTIONS,
} from "~/lib/dashboards/options";
import { realDashboardsRoutes } from "~/lib/dashboards/api";
import { ChatUiContext } from "~/components/chat/chat-ui-context";
import { AnchorTimeField } from "~/components/dashboards/anchor-time-field";
import { TimezoneField } from "~/components/dashboards/timezone-field";
import {
  REAL_DASHBOARD_PUBLISH_API,
  buildPublishRequest,
  describePublishError,
  findPublishedDashboard,
  initialPublishForm,
  publishDatasetRows,
  publishFormProblems,
  refreshableLabel,
  retargetPublishForm,
  type DashboardPublishApi,
  type DashboardPublishForm,
  type PublishDatasetRow,
  type PublishErrorInfo,
} from "~/components/chat/dashboard-publish-form";

/** The API in force for this view: an explicit prop, then the chat UI
 * context override (the fixture harness), then the real module. */
export function useDashboardPublishApi(override?: DashboardPublishApi | null): DashboardPublishApi {
  const ui = useContext(ChatUiContext);
  return override ?? ui?.dashboardsApi ?? REAL_DASHBOARD_PUBLISH_API;
}

type PublishedDashboardState = {
  /** Every dashboard the caller can see; the dialog picks editable targets. */
  dashboards: PublishedDashboard[];
  /** The one published from this chat file, when there is one. */
  published: PublishedDashboard | null;
  loaded: boolean;
  reload: () => Promise<void>;
  /** Record a publish result without a round trip. */
  setPublished: (dashboard: PublishedDashboard) => void;
};

/**
 * Loads the gallery on mount and tracks which dashboard, if any, came from
 * this conversation file. A failed list is silent: the user can still
 * publish, and the dialog reports its own failures.
 */
export function usePublishedDashboard(
  api: DashboardPublishApi,
  conversationId: string,
  fileId: string,
): PublishedDashboardState {
  const [dashboards, setDashboards] = useState<PublishedDashboard[]>([]);
  const [published, setPublishedState] = useState<PublishedDashboard | null>(null);
  const [loaded, setLoaded] = useState(false);
  const alive = useRef(true);
  useEffect(() => {
    alive.current = true;
    return () => {
      alive.current = false;
    };
  }, []);
  const reload = useCallback(async () => {
    try {
      const result = await api.listDashboards();
      if (!alive.current) return;
      setDashboards(result.dashboards);
      setPublishedState(findPublishedDashboard(result.dashboards, conversationId, fileId));
    } catch {
      // Gallery unavailable: nothing to show yet.
    } finally {
      if (alive.current) setLoaded(true);
    }
  }, [api, conversationId, fileId]);
  useEffect(() => {
    if (!conversationId) {
      setLoaded(true);
      return;
    }
    void reload();
  }, [reload, conversationId]);
  const setPublished = useCallback((dashboard: PublishedDashboard) => {
    setPublishedState(dashboard);
    setDashboards((list) => [dashboard, ...list.filter((item) => item.id !== dashboard.id)]);
  }, []);
  return { dashboards, published, loaded, reload, setPublished };
}

/** The inline "Published as <name>" band shown under the file header. */
export function DashboardPublishedStrip({
  dashboard,
  onPublishNewVersion,
}: {
  dashboard: PublishedDashboard;
  onPublishNewVersion: () => void;
}) {
  return (
    <div
      data-testid="chat-dashboard-published"
      data-dashboard-slug={dashboard.slug}
      className="flex flex-wrap items-center gap-x-3 gap-y-1 border-b border-[var(--color-border)] bg-[var(--color-success)]/[0.04] px-3 py-1.5 text-[11.5px]"
    >
      <span className="inline-flex items-center gap-1.5 text-[var(--color-text-muted)]">
        <CheckCircle2 className="h-3.5 w-3.5 text-[var(--color-success)]" />
        Published as{" "}
        <span className="font-medium text-[var(--color-text)]">{dashboard.name}</span>
        {dashboard.current_version_no != null && (
          <span className="text-[var(--color-text-dim)]">v{dashboard.current_version_no}</span>
        )}
      </span>
      <Link
        href={realDashboardsRoutes.dashboard(dashboard.slug)}
        data-testid="chat-dashboard-published-open"
        className="inline-flex items-center gap-1 text-[var(--color-text)] underline decoration-[var(--color-border-active)] underline-offset-2 hover:decoration-[var(--color-text)]"
      >
        Open
        <ExternalLink className="h-3 w-3" />
      </Link>
      <button
        type="button"
        data-testid="chat-dashboard-publish-version"
        onClick={onPublishNewVersion}
        className="ml-auto rounded-md border border-[var(--color-border)] bg-[var(--color-bg-card)] px-2 py-0.5 text-[11px] text-[var(--color-text-muted)] hover:bg-[var(--color-bg-hover)] hover:text-[var(--color-text)]"
      >
        Publish new version
      </button>
    </div>
  );
}

const FIELD =
  "w-full rounded-[8px] border border-[var(--color-border)] bg-[var(--color-bg-input)] px-2.5 py-1.5 text-[12px] text-[var(--color-text)] placeholder:text-[var(--color-text-dim)] focus:outline-none focus-visible:ring-2 focus-visible:ring-[var(--color-text)] disabled:opacity-50";
const LABEL = "mb-1 block text-[11px] font-medium text-[var(--color-text-muted)]";

function Field({ label, htmlFor, children, hint }: { label: string; htmlFor: string; children: ReactNode; hint?: string }) {
  return (
    <div>
      <label htmlFor={htmlFor} className={LABEL}>
        {label}
      </label>
      {children}
      {hint && <p className="mt-1 text-[10.5px] leading-4 text-[var(--color-text-dim)]">{hint}</p>}
    </div>
  );
}

function ChoiceGroup<T extends string>({
  name,
  legend,
  value,
  options,
  onChange,
}: {
  name: string;
  legend: string;
  value: T;
  options: readonly { value: T; label: string; hint: string }[];
  onChange: (value: T) => void;
}) {
  return (
    <fieldset>
      <legend className={LABEL}>{legend}</legend>
      <div className="grid gap-1">
        {options.map((option) => {
          const checked = option.value === value;
          return (
            <label
              key={option.value}
              className={`flex cursor-pointer items-start gap-2 rounded-[8px] border px-2.5 py-1.5 ${
                checked
                  ? "border-[var(--color-border-active)] bg-[var(--color-bg-hover)]"
                  : "border-[var(--color-border)] hover:border-[var(--color-border-hover)]"
              }`}
            >
              <input
                type="radio"
                name={name}
                value={option.value}
                checked={checked}
                onChange={() => onChange(option.value)}
                className="mt-0.5 accent-[var(--color-success)]"
              />
              <span className="min-w-0">
                <span className="block text-[12px] text-[var(--color-text)]">{option.label}</span>
                <span className="block text-[10.5px] leading-4 text-[var(--color-text-dim)]">{option.hint}</span>
              </span>
            </label>
          );
        })}
      </div>
    </fieldset>
  );
}

function DatasetTable({ rows }: { rows: PublishDatasetRow[] }) {
  return (
    <table data-testid="chat-dashboard-publish-datasets" className="w-full text-left text-[11.5px]">
      <thead>
        <tr className="text-[10.5px] uppercase tracking-[0.06em] text-[var(--color-text-dim)]">
          <th className="pb-1 pr-2 font-medium">Dataset</th>
          <th className="pb-1 pr-2 font-medium">Refresh</th>
          <th className="pb-1 font-medium">File</th>
        </tr>
      </thead>
      <tbody>
        {rows.map((row) => (
          <tr
            key={row.name}
            data-testid="chat-dashboard-publish-dataset"
            data-dataset={row.name}
            data-status={row.status}
            className="border-t border-[var(--color-border)]"
          >
            <td className="py-1 pr-2 font-mono text-[var(--color-text)]">{row.name}</td>
            <td className="py-1 pr-2 text-[var(--color-text-muted)]">{refreshableLabel(row)}</td>
            <td className="py-1">
              {row.status === "inline" && <span className="text-[var(--color-text-dim)]">Inline rows</span>}
              {row.status === "found" && (
                <span className="text-[var(--color-text-muted)]">
                  Found <span className="font-mono text-[var(--color-text-dim)]">{row.file?.path}</span>
                </span>
              )}
              {row.status === "missing" && (
                <span className="inline-flex items-center gap-1 text-[var(--color-error)]">
                  <AlertCircle className="h-3 w-3" />
                  Missing <span className="font-mono">{row.path}</span>
                </span>
              )}
            </td>
          </tr>
        ))}
      </tbody>
    </table>
  );
}

export type DashboardPublishDialogProps = {
  open: boolean;
  onClose: () => void;
  conversationId: string;
  file: ConversationFileInfo;
  spec: DashboardSpec;
  files: readonly ConversationFileInfo[];
  /** Dashboards already loaded by the view; the dialog filters to editable. */
  dashboards: readonly PublishedDashboard[];
  /** Preselect this dashboard as the target ("Publish new version"). */
  initialTargetId?: string | null;
  onPublished: (result: { dashboard: PublishedDashboard }) => void;
  api?: DashboardPublishApi | null;
  /** Fixed timezone for deterministic tests; defaults to the browser's. */
  timezone?: string;
};

export function DashboardPublishDialog(props: DashboardPublishDialogProps) {
  if (!props.open) return null;
  return <DashboardPublishDialogBody {...props} />;
}

/** Mounted only while open, so every open starts from a fresh form. */
function DashboardPublishDialogBody({
  onClose,
  conversationId,
  file,
  spec,
  files,
  dashboards,
  initialTargetId,
  onPublished,
  api: apiOverride,
  timezone,
}: DashboardPublishDialogProps) {
  const api = useDashboardPublishApi(apiOverride);
  const ids = useId();
  const panelRef = useRef<HTMLDivElement>(null);
  useFocusTrap(panelRef, true);
  const [mounted, setMounted] = useState(false);
  useEffect(() => setMounted(true), []);

  const editable = useMemo(() => dashboards.filter((dashboard) => dashboard.can_edit && !dashboard.archived_at), [dashboards]);
  const [form, setForm] = useState<DashboardPublishForm>(() => {
    const fresh = initialPublishForm(spec, { timezone });
    return initialTargetId ? retargetPublishForm(fresh, initialTargetId, dashboards) : fresh;
  });
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState<PublishErrorInfo | null>(null);

  const rows = useMemo(
    () => publishDatasetRows(spec, files, { runId: file.origin_run_id }),
    [spec, files, file.origin_run_id],
  );
  const missing = rows.filter((row) => row.status === "missing");
  const anyRefreshable = rows.some((row) => row.refreshable);
  const problems = publishFormProblems(form);
  const blocked = missing.length > 0 || problems.length > 0 || submitting;

  const update = <K extends keyof DashboardPublishForm>(key: K, value: DashboardPublishForm[K]) =>
    setForm((current) => ({ ...current, [key]: value }));

  useEffect(() => {
    const onKey = (event: KeyboardEvent) => {
      if (event.key === "Escape") {
        event.stopPropagation();
        onClose();
      }
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [onClose]);

  const submit = async () => {
    if (blocked) return;
    setSubmitting(true);
    setError(null);
    try {
      const result = await api.publishDashboard(conversationId, file.id, buildPublishRequest(form));
      onPublished(result);
    } catch (caught) {
      setError(describePublishError(caught));
      setSubmitting(false);
    }
  };

  if (!mounted) return null;
  const versioning = form.target !== "new";
  return createPortal(
    <div
      className="fixed inset-0 z-[110] flex items-center justify-center bg-black/70 p-4"
      onClick={onClose}
    >
      <div
        ref={panelRef}
        role="dialog"
        aria-modal="true"
        aria-labelledby={`${ids}-title`}
        data-testid="chat-dashboard-publish-dialog"
        className="flex max-h-[92vh] w-[600px] max-w-[96vw] flex-col overflow-hidden rounded-[14px] border border-[var(--color-border)] bg-[var(--color-bg-card)] shadow-2xl animate-scale-in"
        onClick={(event) => event.stopPropagation()}
      >
        <div className="flex flex-none items-center justify-between border-b border-[var(--color-border)] px-5 py-3">
          <span id={`${ids}-title`} className="inline-flex items-center gap-2 text-[13px] font-medium text-[var(--color-text)]">
            <Upload className="h-3.5 w-3.5 text-[var(--color-success)]" />
            {versioning ? "Publish a new version" : "Publish to the dashboards gallery"}
          </span>
          <button
            type="button"
            aria-label="Close"
            onClick={onClose}
            className="rounded-lg p-1.5 text-[var(--color-text-dim)] hover:bg-[var(--color-bg-hover)] hover:text-[var(--color-text)]"
          >
            <X className="h-4 w-4" />
          </button>
        </div>

        <form
          className="min-h-0 flex-1 space-y-4 overflow-y-auto px-5 py-4"
          onSubmit={(event) => {
            event.preventDefault();
            void submit();
          }}
        >
          <div className="grid grid-cols-1 gap-3 sm:grid-cols-[1fr_200px]">
            <Field label="Name" htmlFor={`${ids}-name`}>
              <input
                id={`${ids}-name`}
                data-testid="chat-dashboard-publish-name"
                value={form.name}
                onChange={(event) => update("name", event.target.value)}
                className={FIELD}
                autoComplete="off"
              />
            </Field>
            <Field label="Target" htmlFor={`${ids}-target`}>
              <select
                id={`${ids}-target`}
                data-testid="chat-dashboard-publish-target"
                value={form.target}
                onChange={(event) => setForm((current) => retargetPublishForm(current, event.target.value, dashboards))}
                className={FIELD}
              >
                <option value="new">New dashboard</option>
                {editable.length > 0 && (
                  <optgroup label="Update existing">
                    {editable.map((dashboard) => (
                      <option key={dashboard.id} value={dashboard.id}>
                        {dashboard.name}
                      </option>
                    ))}
                  </optgroup>
                )}
              </select>
            </Field>
          </div>

          <Field label="Description" htmlFor={`${ids}-description`}>
            <textarea
              id={`${ids}-description`}
              data-testid="chat-dashboard-publish-description"
              value={form.description}
              onChange={(event) => update("description", event.target.value)}
              rows={2}
              className={`${FIELD} resize-y`}
            />
          </Field>

          <ChoiceGroup
            name={`${ids}-visibility`}
            legend="Visibility"
            value={form.visibility}
            options={DASHBOARD_VISIBILITY_OPTIONS}
            onChange={(value) => update("visibility", value)}
          />

          <fieldset className="space-y-3">
            <legend className={LABEL}>Refresh</legend>
            <div className="grid grid-cols-1 gap-3 sm:grid-cols-3">
              <Field label="Interval" htmlFor={`${ids}-interval`}>
                <select
                  id={`${ids}-interval`}
                  data-testid="chat-dashboard-publish-interval"
                  value={form.intervalMinutes ?? "off"}
                  onChange={(event) =>
                    update(
                      "intervalMinutes",
                      event.target.value === "off" ? null : (Number(event.target.value) as DashboardRefreshInterval),
                    )
                  }
                  className={FIELD}
                >
                  {DASHBOARD_REFRESH_OPTIONS.map((option) => (
                    <option key={option.label} value={option.value ?? "off"}>
                      {option.label}
                    </option>
                  ))}
                </select>
              </Field>
              <Field label="Aligned to" htmlFor={`${ids}-anchor`}>
                <AnchorTimeField
                  id={`${ids}-anchor`}
                  testId="chat-dashboard-publish-anchor"
                  value={form.anchorTime}
                  disabled={form.intervalMinutes == null}
                  onChange={(value) => update("anchorTime", value)}
                  className={FIELD}
                />
              </Field>
              <Field label="Timezone" htmlFor={`${ids}-timezone`}>
                <TimezoneField
                  id={`${ids}-timezone`}
                  testId="chat-dashboard-publish-timezone"
                  value={form.timezone}
                  disabled={form.intervalMinutes == null}
                  onChange={(value) => update("timezone", value)}
                  className={FIELD}
                />
              </Field>
            </div>
            <ChoiceGroup
              name={`${ids}-mode`}
              legend="Refresh mode"
              value={form.mode}
              options={DASHBOARD_REFRESH_MODE_OPTIONS}
              onChange={(value) => update("mode", value)}
            />
            {!anyRefreshable && form.mode === "sql" && (
              <p className="text-[10.5px] leading-4 text-[var(--color-warning)]">
                No dataset carries a SQL source, so a SQL re-run keeps every dataset as it is now.
              </p>
            )}
            <label className="flex cursor-pointer items-center gap-2 text-[12px] text-[var(--color-text)]">
              <input
                type="checkbox"
                data-testid="chat-dashboard-publish-notify"
                checked={form.notifyOnFailure}
                onChange={(event) => update("notifyOnFailure", event.target.checked)}
                className="accent-[var(--color-success)]"
              />
              Notify me when a refresh fails
            </label>
          </fieldset>

          <div>
            <p className={LABEL}>Datasets</p>
            <DatasetTable rows={rows} />
          </div>

          {(missing.length > 0 || problems.length > 0 || error) && (
            <div
              role="alert"
              data-testid="chat-dashboard-publish-error"
              className="rounded-md border border-[var(--color-error)]/30 bg-[var(--color-error)]/5 px-3 py-2 text-[11.5px] leading-5 text-[var(--color-error)]"
            >
              {missing.length > 0 && (
                <p>
                  Cannot publish: {missing.length === 1 ? "the dataset file" : "these dataset files"} {missing.map((row) => row.path).join(", ")} {missing.length === 1 ? "is" : "are"} not in this chat. Ask the agent to write {missing.length === 1 ? "it" : "them"} again, then publish.
                </p>
              )}
              {problems.map((problem) => (
                <p key={problem}>{problem}</p>
              ))}
              {error && <p data-testid="chat-dashboard-publish-api-error">{error.message}</p>}
            </div>
          )}
        </form>

        <div className="flex flex-none items-center justify-end gap-2 border-t border-[var(--color-border)] px-5 py-3">
          <button
            type="button"
            onClick={onClose}
            className="rounded-[10px] px-4 py-2 text-[12px] text-[var(--color-text-dim)] transition-colors hover:text-[var(--color-text)] focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-[var(--color-text)]"
          >
            Cancel
          </button>
          <button
            type="button"
            data-testid="chat-dashboard-publish-submit"
            disabled={blocked}
            onClick={() => void submit()}
            className="inline-flex items-center gap-1.5 rounded-[10px] bg-[var(--color-text)] px-4 py-2 text-[12px] font-medium text-[var(--color-bg)] hover:opacity-90 disabled:cursor-not-allowed disabled:opacity-40 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-[var(--color-text)] focus-visible:ring-offset-2 focus-visible:ring-offset-[var(--color-bg-card)]"
          >
            {submitting ? <Loader2 className="h-3.5 w-3.5 animate-spin" /> : <Upload className="h-3.5 w-3.5" />}
            {versioning ? "Publish version" : "Publish"}
          </button>
        </div>
      </div>
    </div>,
    document.body,
  );
}
