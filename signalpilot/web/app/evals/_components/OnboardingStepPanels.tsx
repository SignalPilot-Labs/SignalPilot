"use client";

/** The runtime and run-policy panels of the eval onboarding wizard. */

import Link from "next/link";
import { ExternalLink } from "lucide-react";
import type { ConnectionInfo } from "~/lib/types";
import type { Draft } from "./onboardingDraft";

type StepProps = {
  draft: Draft;
  update: (patch: Partial<Draft>) => void;
};

export function RuntimeStep({
  draft,
  update,
  connections,
  connectionsLoading,
  connectionsError,
}: StepProps & {
  connections: ConnectionInfo[] | undefined;
  connectionsLoading: boolean;
  connectionsError: unknown;
}) {
  const selectedConnection = connections?.find((connection) => connection.name === draft.connection);
  return (
    <div className="ev-onboarding-panel">
      <div className="ev-onboarding-heading">
        <span>03</span>
        <div>
          <h2>Grading runtime</h2>
          <p>Choose the warehouse and execution limits for every run.</p>
        </div>
      </div>
      <div className="ev-onboarding-grid">
        <label className="ev-onboarding-field">
          <span>Warehouse connection</span>
          <select
            value={draft.connection}
            disabled={connectionsLoading || !connections?.length}
            onChange={(event) => update({ connection: event.target.value })}
            data-testid="eval-connection"
          >
            <option value="">{connectionsLoading ? "Loading connections..." : "Select a connection"}</option>
            {connections?.map((connection) => (
              <option key={connection.id} value={connection.name}>
                {connection.name} ({connection.db_type})
              </option>
            ))}
          </select>
          {selectedConnection && (
            <small>{selectedConnection.database || selectedConnection.host || selectedConnection.db_type}</small>
          )}
        </label>
        <label className="ev-onboarding-field">
          <span>Model</span>
          <select value={draft.model} onChange={(event) => update({ model: event.target.value })}>
            <option value="sonnet">Sonnet</option>
            <option value="opus">Opus</option>
            <option value="haiku">Haiku</option>
          </select>
        </label>
        <label className="ev-onboarding-field">
          <span>Max tasks per run</span>
          <input
            type="number"
            min={0}
            max={200}
            value={draft.max_tasks}
            onChange={(event) => update({ max_tasks: Number(event.target.value) || 0 })}
          />
          <small>Use 0 to run the complete set.</small>
        </label>
        <label className="ev-onboarding-field ev-onboarding-field-wide">
          <span>Prompt preamble</span>
          <textarea
            rows={3}
            value={draft.prompt_preamble}
            onChange={(event) => update({ prompt_preamble: event.target.value })}
            placeholder="Use the SignalPilot MCP tools with connection northwind_ro_conn."
          />
        </label>
      </div>
      {!connectionsLoading && !connections?.length && (
        <div className="ev-onboarding-notice">
          <span>{connectionsError ? "Connections could not be loaded." : "Add a warehouse connection before continuing."}</span>
          <Link href="/connections">Open connections <ExternalLink /></Link>
        </div>
      )}
    </div>
  );
}

export function PolicyStep({ draft, update }: StepProps) {
  const project = draft.project.url
    ? `${draft.project.url}${draft.project.ref ? ` @ ${draft.project.ref}` : ""}`
    : "not set";
  return (
    <div className="ev-onboarding-panel">
      <div className="ev-onboarding-heading">
        <span>04</span>
        <div>
          <h2>Run policy</h2>
          <p>Set regression alerts and knowledge-triggered runs.</p>
        </div>
      </div>
      <label className="ev-onboarding-field">
        <span>Notify emails</span>
        <input
          value={draft.notify_emails}
          onChange={(event) => update({ notify_emails: event.target.value })}
          placeholder="data-team@acme.com, oncall@acme.com"
        />
        <small>Separate multiple addresses with commas.</small>
      </label>
      <label className="ev-onboarding-toggle">
        <input
          type="checkbox"
          checked={draft.autorun_on_knowledge_add}
          onChange={(event) => update({ autorun_on_knowledge_add: event.target.checked })}
        />
        <span aria-hidden="true" />
        <div>
          <strong>Autorun after knowledge changes</strong>
          <small>Run the complete set after an entry is added. Changes coalesce for two minutes.</small>
        </div>
      </label>
      <dl className="ev-onboarding-review">
        <div><dt>Source</dt><dd>{draft.repo_url}</dd></div>
        <div><dt>Project</dt><dd>{project}</dd></div>
        <div><dt>Connection</dt><dd>{draft.connection}</dd></div>
        <div><dt>Runtime</dt><dd>{draft.model} / {draft.max_tasks === 0 ? "all tasks" : `${draft.max_tasks} tasks`}</dd></div>
      </dl>
    </div>
  );
}
