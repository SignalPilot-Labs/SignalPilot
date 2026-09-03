"use client";

import { ArrowRight, ChevronRight, Plug, Settings2, X } from "lucide-react";
import Link from "next/link";
import { useId, type Dispatch, type SetStateAction } from "react";
import type { Connector } from "~/lib/api/mcp-connectors";
import type {
  StandaloneChatEffort,
  StandaloneChatEffortOption,
  StandaloneChatModel,
  StandaloneChatModelOption,
} from "~/lib/api";
import {
  deriveConnectorHealth,
  describeNextChatTools,
  describeToolCount,
} from "~/lib/mcp-connectors-state";
import { Skeleton } from "~/components/ui/skeleton";
import { Switch } from "~/components/ui/switch";
import { ConnectorGlyph } from "~/components/connectors/connector-glyph";
import { ConnectorStatusPill } from "~/components/connectors/connector-status-pill";
import {
  useConnectors,
  useOptionalConnectors,
} from "~/components/connectors/connectors-context";
import { useConnectorActions } from "~/components/connectors/use-connector-actions";
import { Chip, Eyebrow, FOCUS_RING } from "~/components/connectors/ui";
import {
  CHAT_TELEMETRY_AVAILABLE,
  setChatTelemetryEnabled,
  useChatTelemetrySetting,
} from "~/components/chat/use-chat-telemetry-setting";

export type ChatBudgetSettings = {
  perQueryBudgetUsd: number;
  setPerQueryBudgetUsd: Dispatch<SetStateAction<number>>;
  chatBudgetUsd: number;
  setChatBudgetUsd: Dispatch<SetStateAction<number>>;
};

export type ChatModelSettings = {
  value: StandaloneChatModel;
  options: StandaloneChatModelOption[];
  disabled: boolean;
  onChange: (model: StandaloneChatModel) => void;
  effort: StandaloneChatEffort;
  effortOptions: StandaloneChatEffortOption[];
  onEffortChange: (effort: StandaloneChatEffort) => void;
};

const MANAGE_HREF = "/settings/connectors";

/** Deep link into the settings page's drawer for one connector. */
export function connectorDeepLink(manageHref: string, id: string): string {
  return `${manageHref}${manageHref.includes("?") ? "&" : "?"}open=${encodeURIComponent(id)}`;
}

const SMALL_BUTTON = `min-h-[30px] rounded-[8px] px-2.5 text-[11.5px] font-medium disabled:opacity-50 ${FOCUS_RING}`;

function ConnectorRow({ connector, manageHref }: { connector: Connector; manageHref: string }) {
  const actions = useConnectorActions();
  const health = deriveConnectorHealth(connector);
  const onForMe = connector.my_state?.enabled ?? true;
  const busy = actions.isBusy(connector.id);
  const toolsOn = Math.max(0, connector.enabled_tool_count - (connector.my_state?.disabled_tools.length ?? 0));
  const href = connectorDeepLink(manageHref, connector.id);

  // A row whose state needs fixing shows the fix, not a green switch that
  // reads as healthy. The settings page uses the same rule.
  const control =
    health.action === "sign_in" ? (
      <button
        type="button"
        data-testid="chat-settings-sign-in"
        disabled={busy}
        onClick={() => void actions.signIn(connector)}
        className={`${SMALL_BUTTON} bg-[var(--color-text)] text-[var(--color-bg)] hover:bg-[var(--color-accent-hover)]`}
      >
        Sign in
      </button>
    ) : health.action === "retry" ? (
      <button
        type="button"
        data-testid="chat-settings-retry"
        disabled={busy}
        onClick={() => void actions.retry(connector)}
        className={`${SMALL_BUTTON} border border-[var(--color-border)] bg-[var(--color-bg-card)] text-[var(--color-text)] hover:border-[var(--color-border-hover)]`}
      >
        Retry
      </button>
    ) : health.action === "review" || health.action === "add_key" ? (
      <Link
        href={href}
        data-testid={health.action === "review" ? "chat-settings-review" : "chat-settings-add-key"}
        className={`${SMALL_BUTTON} inline-flex items-center border border-[var(--color-border)] bg-[var(--color-bg-card)] text-[var(--color-text)] hover:border-[var(--color-border-hover)]`}
      >
        {health.action === "review" ? "Review" : "Add key"}
      </Link>
    ) : (
      <Switch
        size="sm"
        checked={onForMe}
        disabled={!connector.enabled}
        busy={busy}
        aria-label={`On for me: ${connector.name}`}
        data-testid="chat-settings-on-for-me"
        onCheckedChange={(next) => void actions.toggleForMe(connector, next)}
      />
    );

  return (
    <li
      data-testid="chat-settings-connector-row"
      data-connector-id={connector.id}
      className="group relative flex min-h-[52px] items-center gap-3 rounded-[var(--radius-ctl)] px-2 py-1.5 transition-colors hover:bg-[var(--color-bg-hover)] focus-within:bg-[var(--color-bg-hover)]"
    >
      <ConnectorGlyph connector={connector} size={28} />
      <div className="min-w-0 flex-1">
        <div className="flex min-w-0 items-center gap-1.5">
          <Link
            href={href}
            data-testid="chat-settings-connector-link"
            aria-label={`${connector.name}: open in Connectors`}
            className={`truncate rounded-[4px] text-[12.5px] font-medium text-[var(--color-text)] after:absolute after:inset-0 after:content-[''] ${FOCUS_RING} focus-visible:ring-offset-0`}
          >
            {connector.name}
          </Link>
          {connector.scope === "org" && <Chip>Organization</Chip>}
        </div>
        <div className="mt-0.5 flex min-w-0 items-center gap-1.5">
          <ConnectorStatusPill health={health} size="sm" />
          <span className="truncate text-[11px] tabular-nums text-[var(--color-text-dim)]" data-testid="chat-settings-row-tools">
            {describeToolCount(connector.tool_count, toolsOn)}
          </span>
        </div>
      </div>
      <div className="relative z-10 flex-none">{control}</div>
      <ChevronRight
        className="hidden h-3.5 w-3.5 flex-none text-[var(--color-text-dim)] opacity-0 transition-opacity group-hover:opacity-100 group-focus-within:opacity-100 sm:block"
        aria-hidden="true"
      />
    </li>
  );
}

function ConnectorRows({ manageHref }: { manageHref: string }) {
  const store = useConnectors();
  if (store.loading) {
    return (
      <div className="space-y-1.5" aria-busy="true">
        {[0, 1, 2].map((i) => (
          <div key={i} className="flex items-center gap-3 rounded-[var(--radius-ctl)] px-2 py-2">
            <Skeleton className="h-7 w-7 rounded-[8px]" />
            <div className="flex-1 space-y-1.5">
              <Skeleton className="h-2.5 w-24" />
              <Skeleton className="h-2 w-16" />
            </div>
            <Skeleton className="h-4 w-8 rounded-full" />
          </div>
        ))}
      </div>
    );
  }
  if (store.error) {
    return (
      <p role="alert" className="text-[12px] text-[var(--color-error)]">
        We couldn&apos;t load your connectors. {store.error}
      </p>
    );
  }
  if (store.connectors.length === 0) {
    return (
      <div
        data-testid="chat-settings-connectors-empty"
        className="rounded-[var(--radius-card)] border border-dashed border-[var(--color-border)] px-4 py-5 text-center"
      >
        <Plug className="mx-auto h-5 w-5 text-[var(--color-text-dim)]" aria-hidden="true" />
        <p className="mt-2 text-[13px] font-medium text-[var(--color-text)]">No connectors yet</p>
        <p className="mt-1 text-[12px] leading-5 text-[var(--color-text-dim)]">
          Give the agent tools from Jira, GitHub, Slack, or any server with a URL.
        </p>
        <Link
          href={manageHref}
          className={`mt-3 inline-flex min-h-[34px] items-center gap-1.5 rounded-[var(--radius-ctl)] bg-[var(--color-text)] px-3 text-[12px] font-medium text-[var(--color-bg)] hover:bg-[var(--color-accent-hover)] ${FOCUS_RING}`}
        >
          Add a connector
          <ArrowRight className="h-3.5 w-3.5" aria-hidden="true" />
        </Link>
      </div>
    );
  }
  return (
    <>
      <p className="text-[11.5px] text-[var(--color-text-muted)]" data-testid="chat-settings-summary">
        {describeNextChatTools(store.connectors)}
      </p>
      <ul className="space-y-0.5" data-testid="chat-settings-connectors">
        {store.connectors.map((connector) => (
          <ConnectorRow key={connector.id} connector={connector} manageHref={manageHref} />
        ))}
      </ul>
    </>
  );
}

function BudgetsSection({ budgets }: { budgets: ChatBudgetSettings }) {
  const perId = useId();
  const chatId = useId();
  const input =
    "min-h-[36px] w-full rounded-[var(--radius-ctl)] border border-[var(--color-border)] bg-[var(--color-bg-input)] px-2.5 text-[12.5px] tabular-nums text-[var(--color-text)] focus:border-[var(--color-border-active)] focus:!shadow-none focus:outline-none";
  return (
    <section aria-labelledby="chat-settings-budgets" className="space-y-3">
      <div>
        <Eyebrow>
          <span id="chat-settings-budgets">Query budgets</span>
        </Eyebrow>
        <p className="mt-1 text-[11.5px] text-[var(--color-text-dim)]">For the next chat you start.</p>
      </div>
      <div className="grid grid-cols-2 gap-3">
        <label htmlFor={perId} className="block">
          <span className="mb-1 block text-[11.5px] text-[var(--color-text-muted)]">Per query (USD)</span>
          <input
            id={perId}
            type="number"
            min="0"
            step="0.01"
            value={budgets.perQueryBudgetUsd}
            onChange={(e) => budgets.setPerQueryBudgetUsd(Math.max(0, Number(e.target.value)))}
            className={input}
          />
        </label>
        <label htmlFor={chatId} className="block">
          <span className="mb-1 block text-[11.5px] text-[var(--color-text-muted)]">Whole chat (USD)</span>
          <input
            id={chatId}
            type="number"
            min={budgets.perQueryBudgetUsd}
            step="0.01"
            value={budgets.chatBudgetUsd}
            onChange={(e) => budgets.setChatBudgetUsd(Math.max(budgets.perQueryBudgetUsd, Number(e.target.value)))}
            className={input}
          />
        </label>
      </div>
    </section>
  );
}

function ModelSection({ model }: { model: ChatModelSettings }) {
  const selectId = useId();
  const effortSelectId = useId();
  return (
    <section aria-labelledby="chat-settings-model" className="space-y-3">
      <div>
        <Eyebrow>
          <span id="chat-settings-model">Model</span>
        </Eyebrow>
        <p className="mt-1 text-[11.5px] text-[var(--color-text-dim)]">
          Used for every turn in this chat.
        </p>
      </div>
      <label htmlFor={selectId} className="block">
        <span className="sr-only">Chat model</span>
        <select
          id={selectId}
          data-testid="chat-settings-model-select"
          value={model.value}
          disabled={model.disabled}
          onChange={(event) =>
            model.onChange(event.target.value as StandaloneChatModel)
          }
          className="min-h-[38px] w-full rounded-[var(--radius-ctl)] border border-[var(--color-border)] bg-[var(--color-bg-input)] px-2.5 text-[12.5px] text-[var(--color-text)] focus:border-[var(--color-border-active)] focus:outline-none disabled:cursor-not-allowed disabled:opacity-50"
        >
          {model.options.map((option) => (
            <option key={option.id} value={option.id}>
              {option.label}
            </option>
          ))}
        </select>
      </label>
      <label htmlFor={effortSelectId} className="block">
        <span className="mb-1 block text-[11.5px] text-[var(--color-text-muted)]">
          Thinking level
        </span>
        <select
          id={effortSelectId}
          data-testid="chat-settings-effort-select"
          value={model.effort}
          disabled={model.disabled}
          onChange={(event) =>
            model.onEffortChange(event.target.value as StandaloneChatEffort)
          }
          className="min-h-[38px] w-full rounded-[var(--radius-ctl)] border border-[var(--color-border)] bg-[var(--color-bg-input)] px-2.5 text-[12.5px] text-[var(--color-text)] focus:border-[var(--color-border-active)] focus:outline-none disabled:cursor-not-allowed disabled:opacity-50"
        >
          {model.effortOptions.map((option) => (
            <option key={option.id} value={option.id}>
              {option.label}
            </option>
          ))}
        </select>
        <span className="mt-1 block text-[11px] leading-4 text-[var(--color-text-dim)]">
          Higher levels spend longer reasoning before acting. Medium is the default.
        </span>
      </label>
      {model.disabled && (
        <p className="text-[11px] text-[var(--color-text-dim)]">
          You can switch models after the current run finishes.
        </p>
      )}
    </section>
  );
}

function TelemetrySection() {
  const enabled = useChatTelemetrySetting();
  if (!CHAT_TELEMETRY_AVAILABLE) return null;

  return (
    <section aria-labelledby="chat-settings-telemetry" className="space-y-3">
      <Eyebrow>
        <span id="chat-settings-telemetry">Diagnostics</span>
      </Eyebrow>
      <div className="flex items-center justify-between gap-4">
        <div>
          <p className="text-[12.5px] font-medium text-[var(--color-text)]">
            Chat telemetry
          </p>
          <p className="mt-0.5 text-[11.5px] leading-5 text-[var(--color-text-dim)]">
            Show live timing and token diagnostics. Saved only in this browser.
          </p>
        </div>
        <Switch
          checked={enabled}
          onCheckedChange={setChatTelemetryEnabled}
          aria-label="Enable chat telemetry"
          data-testid="chat-settings-telemetry-toggle"
        />
      </div>
    </section>
  );
}

/**
 * Right-side "Chat settings" panel — the same slot family as the artifacts
 * panel. Connectors first (a one-line "what your next chat gets" summary,
 * then rows that deep-link to the settings page and carry an "On for me"
 * switch or the one fix the row needs), then the query-budget fields when
 * the chat exposes them.
 */
export function ChatSettingsPanel({
  onClose,
  connectorsEnabled,
  model,
  budgets,
  manageHref = MANAGE_HREF,
}: {
  onClose: () => void;
  connectorsEnabled: boolean;
  model: ChatModelSettings;
  budgets?: ChatBudgetSettings | null;
  manageHref?: string;
}) {
  // Rows need the connectors store; without a provider the section still
  // renders, pointing at the settings page instead of failing.
  const store = useOptionalConnectors();
  return (
    <>
      {/* Under lg the panel floats over the chat; the backdrop closes it. */}
      <div
        aria-hidden="true"
        onClick={onClose}
        className="fixed inset-0 z-[70] bg-black/50 lg:hidden"
      />
    <aside
      data-testid="chat-settings-panel"
      aria-label="Chat settings"
      className="fixed inset-y-0 right-0 z-[80] flex w-full flex-col border-l border-[var(--color-border)] bg-[var(--color-bg)] shadow-2xl shadow-black/50 animate-slide-in-right md:w-[380px] lg:static lg:z-auto lg:w-[380px] lg:min-w-[340px] lg:max-w-[440px] lg:flex-none lg:shadow-none"
    >
      <div className="flex h-11 flex-none items-center justify-between border-b border-[var(--color-border)] px-3">
        <div className="flex min-w-0 items-center gap-2">
          <Settings2 className="h-3.5 w-3.5 flex-none text-[var(--color-text-dim)]" aria-hidden="true" />
          <span className="truncate text-xs font-medium text-[var(--color-text)]">Chat settings</span>
        </div>
        <button
          type="button"
          onClick={onClose}
          aria-label="Close chat settings"
          data-testid="chat-settings-close"
          className={`rounded p-1.5 text-[var(--color-text-dim)] transition-colors hover:bg-[var(--color-bg-hover)] hover:text-[var(--color-text)] ${FOCUS_RING}`}
        >
          <X className="h-3.5 w-3.5" aria-hidden="true" />
        </button>
      </div>
      <div className="min-h-0 flex-1 space-y-7 overflow-y-auto px-4 py-4">
        <ModelSection model={model} />
        {connectorsEnabled && (
          <section aria-labelledby="chat-settings-connectors-title" className="space-y-3">
            <div className="flex items-end justify-between gap-3">
              <div>
                <Eyebrow>
                  <span id="chat-settings-connectors-title">Connectors</span>
                </Eyebrow>
                <p className="mt-1 text-[11.5px] text-[var(--color-text-dim)]">
                  Available in all your chats. Changes apply to new chats.
                </p>
              </div>
              <Link
                href={manageHref}
                data-testid="chat-settings-manage"
                className={`flex-none text-[11.5px] text-[var(--color-text-muted)] hover:text-[var(--color-text)] ${FOCUS_RING} rounded`}
              >
                Manage connectors →
              </Link>
            </div>
            {store ? (
              <ConnectorRows manageHref={manageHref} />
            ) : (
              <p className="text-[12px] text-[var(--color-text-dim)]">
                Manage connectors from{" "}
                <Link href={manageHref} className="text-[var(--color-text)] underline underline-offset-4">
                  Settings
                </Link>
                .
              </p>
            )}
          </section>
        )}
        {budgets && <BudgetsSection budgets={budgets} />}
        <TelemetrySection />
      </div>
    </aside>
    </>
  );
}
