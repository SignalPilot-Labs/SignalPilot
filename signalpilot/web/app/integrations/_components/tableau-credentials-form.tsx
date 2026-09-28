"use client";

import type { FormEvent } from "react";
import { Loader2, PlugZap } from "lucide-react";
import type { TableauIntegrationState } from "./use-tableau-integration";

const INPUT =
  "w-full px-3 py-2 bg-[var(--color-bg-input)] border border-[var(--color-border)] rounded-[10px] text-xs font-mono focus:outline-none disabled:opacity-40";
const LABEL = "block text-[12px] text-[var(--color-text-dim)] mb-1.5";
const HELP = "mt-1 text-[11px] text-[var(--color-text-muted)]";

/** Site URL + personal access token fields and the "Save and test" button. */
export function TableauCredentialsForm({ state }: { state: TableauIntegrationState }) {
  const configured = Boolean(state.info?.configured);
  const busy = state.saving;

  function onSubmit(event: FormEvent) {
    event.preventDefault();
    void state.handleSave();
  }

  return (
    <form
      onSubmit={onSubmit}
      data-testid="tableau-form"
      className={`space-y-3 ${configured ? "border-t border-[var(--color-border)] pt-4" : ""}`}
    >
      <div>
        <label htmlFor="tableau-site-url" className={LABEL}>Site URL</label>
        <input
          id="tableau-site-url"
          type="text"
          inputMode="url"
          value={state.siteUrl}
          onChange={(event) => state.setSiteUrl(event.target.value)}
          disabled={busy}
          placeholder="https://10ay.online.tableau.com/#/site/your-site"
          autoComplete="off"
          aria-describedby="tableau-site-url-help"
          className={INPUT}
        />
        <p id="tableau-site-url-help" className={HELP}>Paste any URL from your Tableau site.</p>
      </div>
      <div className="grid gap-3 sm:grid-cols-2">
        <div>
          <label htmlFor="tableau-pat-name" className={LABEL}>Token name</label>
          <input
            id="tableau-pat-name"
            type="text"
            value={state.patName}
            onChange={(event) => state.setPatName(event.target.value)}
            disabled={busy}
            autoComplete="off"
            className={INPUT}
          />
        </div>
        <div>
          <label htmlFor="tableau-pat-secret" className={LABEL}>Token secret</label>
          <input
            id="tableau-pat-secret"
            type="password"
            value={state.patSecret}
            onChange={(event) => state.setPatSecret(event.target.value)}
            disabled={busy}
            autoComplete="new-password"
            aria-describedby={configured ? "tableau-pat-secret-help" : undefined}
            className={INPUT}
          />
          {configured && (
            <p id="tableau-pat-secret-help" className={HELP}>Saved. Leave blank to keep it.</p>
          )}
        </div>
      </div>

      {state.actionError && (
        <p
          role="alert"
          data-testid="tableau-error"
          className="text-[12px] text-[var(--color-error)] break-words"
        >
          {state.actionError}
        </p>
      )}

      <div className="flex justify-end">
        <button
          type="submit"
          disabled={!state.canSave}
          className="flex items-center justify-center gap-2 px-4 py-2 bg-[var(--color-text)] text-[var(--color-bg)] text-[12px] rounded-[10px] transition-opacity duration-150 hover:opacity-90 disabled:opacity-30"
        >
          {busy ? <Loader2 className="w-3 h-3 animate-spin" /> : <PlugZap className="w-3 h-3" />}
          Save and test
        </button>
      </div>
    </form>
  );
}
