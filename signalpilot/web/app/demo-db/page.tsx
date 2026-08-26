"use client";

/**
 * Hidden demo-onboarding page at /demo-db (not linked from the sidebar). Walks
 * a new user from nothing to an agent querying their own sandbox warehouse:
 *   1. pick a demo warehouse — one click forks a private Xata branch of it and
 *      registers it as a connection (once per warehouse; removing the
 *      connection deletes the branch)
 *   2. clone the companion dbt project for that warehouse
 *   3. create an API key and point an agent at the MCP endpoint
 *
 * The branch is the user's alone: the shared warehouse's `main` is never
 * writable, and the gateway holds the Xata credentials — they are never sent
 * to the browser.
 */

import { useCallback, useEffect, useState } from "react";
import Link from "next/link";
import {
  CheckCircle2,
  Database,
  GitBranch,
  KeyRound,
  Loader2,
  Lock,
  Plus,
  Sparkles,
  Trash2,
} from "lucide-react";
import { PageHeader } from "~/components/ui/page-header";
import { ConfirmDialog } from "~/components/ui/confirm-dialog";
import { useToast } from "~/components/ui/toast";
import { CopyButton } from "~/components/ui/copy-button";
import { createDemoConnector, deleteConnection, getDemoConnector } from "~/lib/api";
import type { DemoConnectorStatus, DemoWarehouse } from "~/lib/types";

const GATEWAY_URL = process.env.NEXT_PUBLIC_GATEWAY_URL || "http://localhost:3300";

/**
 * Showcase prompts per demo warehouse (keyed by catalog slug). Three workflows each:
 * build on the private branch, investigate/verify a number, and the knowledge-base
 * loop (the load prompt is the same one the benchmark harness uses to warm a
 * workspace — see benchmark/runners/kb_generator.py).
 */
const DEMO_PROMPTS: Record<
  string,
  { title: string; hint: string; prompt: string }[]
> = {
  contoso: [
    {
      title: "build the warehouse on your branch",
      hint: "governed credential handoff + 180-model build + post-build verification",
      prompt:
        "Use the SignalPilot get_dbt_profile tool to wire dbt to my contoso-demo connection, then run dbt build from the contoso-demo repo. When it finishes, tell me the total attributed revenue by client, in USD.",
    },
    {
      title: "investigate a number before you report it",
      hint: "grain checks + mart-vs-raw reconciliation across 4 wire dialects",
      prompt:
        "How many enrollments (subject-experiment assignments) does drift_labs have? Reconcile the built models against the raw blobs before you commit to a number.",
    },
    {
      title: "load the knowledge base, then use it",
      hint: "map the project into the KB; add an org policy in Knowledge, then ask a policy question",
      prompt:
        "Explore and map out this dbt project for my knowledge base. The project is contoso-demo. Research every model, source table, macro, and data pattern. Populate the knowledge base with everything a future agent would need to build models correctly in this project.",
    },
  ],
  northwind: [
    {
      title: "build the revenue-cycle marts on your branch",
      hint: "9 hospital clients, 4 encounter dialects, money-unit + denial-code landmines",
      prompt:
        "Use the SignalPilot get_dbt_profile tool to wire dbt to my northwind-demo connection and build the staging models from raw.client_blob. Then tell me total billed charges by client, in USD.",
    },
    {
      title: "investigate a number before you report it",
      hint: "claim-grain checks: service-line fan-outs and resubmission duplicates",
      prompt:
        "What's our org-wide claim denial rate by payer? Verify the claim grain and the denial encoding against the raw data before you commit to numbers.",
    },
    {
      title: "load the knowledge base, then use it",
      hint: "map the project into the KB; add reporting policies (fiscal year, KPI definitions), then ask",
      prompt:
        "Explore and map out this dbt project for my knowledge base. The project is northwind-demo. Research every model, source table, macro, and data pattern. Populate the knowledge base with everything a future agent would need to build models correctly in this project.",
    },
  ],
};

function StepCard({
  step,
  icon,
  title,
  done,
  children,
}: {
  step: number;
  icon: React.ReactNode;
  title: string;
  done?: boolean;
  children: React.ReactNode;
}) {
  return (
    <div className="border border-[var(--color-border)] bg-[var(--color-bg-card)] rounded-[14px] p-5">
      <div className="flex items-center gap-2.5 mb-3">
        <span
          className={`w-6 h-6 rounded-full flex items-center justify-center text-[11px] font-mono border ${
            done
              ? "border-[var(--color-success)]/40 text-[var(--color-success)]"
              : "border-[var(--color-border)] text-[var(--color-text-dim)]"
          }`}
        >
          {step}
        </span>
        <span className="text-[var(--color-text-dim)]">{icon}</span>
        <h2 className="text-[14px] font-medium text-[var(--color-text)]">{title}</h2>
      </div>
      <div className="pl-[34px]">{children}</div>
    </div>
  );
}

function CodeSnippet({ label, code }: { label: string; code: string }) {
  return (
    <div className="mb-3">
      <div className="flex items-center justify-between mb-1.5">
        <span className="text-[11px] text-[var(--color-text-dim)]">{label}</span>
        <CopyButton text={code} label="copy" />
      </div>
      <pre className="px-3 py-2.5 bg-[var(--color-bg)] border border-[var(--color-border)] rounded-[10px] text-[11px] text-[var(--color-text-muted)] font-mono overflow-x-auto whitespace-pre">
{code}
      </pre>
    </div>
  );
}

function WarehouseRow({
  demo,
  busy,
  onAdd,
  onRemove,
}: {
  demo: DemoWarehouse;
  busy: boolean;
  onAdd: () => void;
  onRemove: () => void;
}) {
  return (
    <div className="flex items-start justify-between gap-4 py-3 border-b border-[var(--color-border)] last:border-b-0">
      <div className="min-w-0">
        <div className="flex items-center gap-2">
          <span className="text-[13px] font-medium text-[var(--color-text)]">{demo.title}</span>
          {demo.exists && (
            <CheckCircle2 className="w-3.5 h-3.5 text-[var(--color-success)]" strokeWidth={2} />
          )}
        </div>
        {demo.description && (
          <p className="text-[12px] text-[var(--color-text-dim)] mt-0.5">{demo.description}</p>
        )}
        {demo.exists && (
          <p className="text-[11.5px] text-[var(--color-text-muted)] mt-1.5 leading-relaxed">
            connection <code className="text-[var(--color-success)]">{demo.connection_name}</code> on
            your private branch <code className="text-[var(--color-success)]">{demo.branch ?? "?"}</code>
          </p>
        )}
      </div>
      {demo.exists ? (
        <button
          onClick={onRemove}
          disabled={busy}
          className="shrink-0 flex items-center gap-1.5 px-3 py-1.5 rounded-[10px] text-[12px] text-[var(--color-error)] border border-[var(--color-error)]/30 hover:bg-[var(--color-error)]/10 transition-colors duration-150 disabled:opacity-50"
        >
          {busy ? <Loader2 className="w-3 h-3 animate-spin" /> : <Trash2 className="w-3 h-3" />}
          remove
        </button>
      ) : (
        <button
          onClick={onAdd}
          disabled={busy}
          className="shrink-0 flex items-center gap-1.5 px-3.5 py-1.5 rounded-[10px] text-[12px] font-medium text-[var(--color-bg)] bg-[var(--color-text)] hover:opacity-90 transition-opacity duration-150 disabled:opacity-50"
        >
          {busy ? <Loader2 className="w-3 h-3 animate-spin" /> : <Plus className="w-3 h-3" />}
          add
        </button>
      )}
    </div>
  );
}

export default function AddDemoConnectorPage() {
  const { toast } = useToast();
  const [status, setStatus] = useState<DemoConnectorStatus | null>(null);
  const [loading, setLoading] = useState(true);
  const [busySlug, setBusySlug] = useState<string | null>(null);
  const [confirmRemove, setConfirmRemove] = useState<DemoWarehouse | null>(null);

  const refresh = useCallback(async () => {
    try {
      setStatus(await getDemoConnector());
    } catch {
      toast("could not reach the gateway", "error");
    } finally {
      setLoading(false);
    }
  }, [toast]);

  useEffect(() => {
    void refresh();
  }, [refresh]);

  async function handleAdd(demo: DemoWarehouse) {
    setBusySlug(demo.slug);
    try {
      const created = await createDemoConnector(demo.slug);
      toast(`${created.title} added on branch ${created.branch}`, "success");
      await refresh();
    } catch (e) {
      const msg = e instanceof Error ? e.message : String(e);
      toast(
        msg.includes("409")
          ? `you have already added the ${demo.title} demo`
          : `failed to add ${demo.title}: ${msg}`,
        "error",
      );
      await refresh();
    } finally {
      setBusySlug(null);
    }
  }

  async function handleRemove(demo: DemoWarehouse) {
    setConfirmRemove(null);
    setBusySlug(demo.slug);
    try {
      await deleteConnection(demo.connection_name);
      toast(`${demo.title} removed — its database branch was deleted`, "success");
      await refresh();
    } catch (e) {
      toast(`failed to remove ${demo.title}: ${e instanceof Error ? e.message : e}`, "error");
    } finally {
      setBusySlug(null);
    }
  }

  const demos = status?.demos ?? [];
  const added = demos.filter((d) => d.exists);
  const mcpUrl = `${GATEWAY_URL}/mcp`;

  return (
    <div className="p-8 max-w-3xl animate-fade-in">
      <PageHeader
        title="Try SignalPilot"
        subtitle="demo"
        description="Get a private sandbox copy of a demo warehouse and a dbt project to work on."
      />

      {loading ? (
        <div className="flex items-center gap-2 text-[13px] text-[var(--color-text-dim)]">
          <Loader2 className="w-4 h-4 animate-spin" /> loading…
        </div>
      ) : (
        <div className="space-y-4">
          {status && !status.enabled && (
            <div className="border border-[var(--color-warning)]/30 bg-[var(--color-warning)]/5 rounded-[14px] p-4 text-[12px] text-[var(--color-warning)]">
              the demo connector is not configured on this gateway (XATA_KEY /
              SP_DEMO_XATA_ORG / SP_DEMO_CATALOG).
            </div>
          )}

          {/* Step 1 — pick a warehouse */}
          <StepCard
            step={1}
            icon={<Database className="w-4 h-4" strokeWidth={1.5} />}
            title="Add a demo warehouse"
            done={added.length > 0}
          >
            <p className="text-[12.5px] text-[var(--color-text-muted)] leading-relaxed mb-1">
              each one forks a private branch of a shared demo database (instant, copy-on-write)
              and registers it as a SignalPilot connection. it is yours alone — query it, break it,
              rebuild it. removing the connection deletes your branch.
            </p>
            {demos.length === 0 && status?.enabled && (
              <p className="text-[12px] text-[var(--color-text-dim)] py-2">
                no demo warehouses are configured.
              </p>
            )}
            <div className="mt-2">
              {demos.map((d) => (
                <WarehouseRow
                  key={d.slug}
                  demo={d}
                  busy={busySlug === d.slug}
                  onAdd={() => void handleAdd(d)}
                  onRemove={() => setConfirmRemove(d)}
                />
              ))}
            </div>
            {added.length > 0 && (
              <p className="text-[11.5px] text-[var(--color-text-dim)] mt-3 flex items-start gap-1.5">
                <Lock className="w-3 h-3 mt-[2px] shrink-0" />
                you have read and write access to your own branch. the shared warehouse itself is
                read-only, and the database credentials stay on the gateway — they are never shown
                here or to your agent.
              </p>
            )}
          </StepCard>

          {/* Step 2 — clone the repo */}
          <StepCard
            step={2}
            icon={<GitBranch className="w-4 h-4" strokeWidth={1.5} />}
            title="Clone the demo dbt project"
            done={added.length > 0}
          >
            <p className="text-[12.5px] text-[var(--color-text-muted)] leading-relaxed mb-3">
              each warehouse comes with a dbt project so you have something real to build on.
            </p>
            {added.length === 0 ? (
              <p className="text-[12px] text-[var(--color-text-dim)]">
                add a warehouse above to see its clone command.
              </p>
            ) : (
              added
                .filter((d) => d.repo_url)
                .map((d) => {
                  const dir = d.repo_url!.split("/").pop()?.replace(/\.git$/, "") || d.slug;
                  return (
                    <CodeSnippet
                      key={d.slug}
                      label={`${d.title} — terminal`}
                      code={`git clone ${d.repo_url}\ncd ${dir}`}
                    />
                  );
                })
            )}
          </StepCard>

          {/* Step 3 — connect your agent */}
          <StepCard
            step={3}
            icon={<KeyRound className="w-4 h-4" strokeWidth={1.5} />}
            title="Connect your agent via MCP"
          >
            <p className="text-[12.5px] text-[var(--color-text-muted)] leading-relaxed mb-3">
              go to{" "}
              <Link href="/settings/api-keys" className="underline hover:text-[var(--color-text)]">
                settings → api keys
              </Link>{" "}
              and create a new key. the page shows your MCP connection URL and ready-made
              snippets. with your key in hand, it looks like this:
            </p>
            <CodeSnippet
              label="claude code — one-liner"
              code={`claude mcp add --transport http signalpilot ${mcpUrl} --header "Authorization: Bearer <your-api-key>"`}
            />
            <CodeSnippet label="mcp connection url" code={mcpUrl} />
            <p className="text-[11px] text-[var(--color-text-dim)] flex items-center gap-1.5">
              <Sparkles className="w-3 h-3" />
              then ask your agent to explore{" "}
              {added.length > 0 ? (
                <code>{added[0].connection_name}</code>
              ) : (
                "your demo connection"
              )}{" "}
              — it is yours to break.
            </p>
          </StepCard>

          {/* Step 4 — try these workflows */}
          {added.some((d) => DEMO_PROMPTS[d.slug]) && (
            <StepCard
              step={4}
              icon={<Sparkles className="w-4 h-4" strokeWidth={1.5} />}
              title="Try these workflows"
            >
              <p className="text-[12.5px] text-[var(--color-text-muted)] leading-relaxed mb-3">
                three prompts per warehouse, in order: build it, interrogate it, then teach
                it your business via the knowledge base. paste them into your connected agent.
              </p>
              {added
                .filter((d) => DEMO_PROMPTS[d.slug])
                .map((d) => (
                  <div key={d.slug} className="mb-4 last:mb-0">
                    <div className="text-[12px] font-medium text-[var(--color-text)] mb-1.5">
                      {d.title}
                    </div>
                    {DEMO_PROMPTS[d.slug].map((p, i) => (
                      <div key={i} className="mb-3">
                        <div className="flex items-center justify-between mb-1">
                          <span className="text-[11px] text-[var(--color-text-dim)]">
                            {i + 1}. {p.title} — {p.hint}
                          </span>
                          <CopyButton text={p.prompt} label="copy" />
                        </div>
                        <pre className="px-3 py-2 bg-[var(--color-bg)] border border-[var(--color-border)] rounded-[10px] text-[11px] text-[var(--color-text-muted)] font-mono overflow-x-auto whitespace-pre-wrap">
{p.prompt}
                        </pre>
                      </div>
                    ))}
                  </div>
                ))}
              <p className="text-[11px] text-[var(--color-text-dim)]">
                the knowledge-base prompt is the same one our benchmark harness uses to warm a
                workspace. after it runs, add a reporting policy of your own under Knowledge and
                ask a question that depends on it — that&apos;s the part no bare agent can do.
              </p>
            </StepCard>
          )}
        </div>
      )}

      <ConfirmDialog
        open={confirmRemove !== null}
        title="remove demo connection"
        message={`this deletes connection '${confirmRemove?.connection_name}' AND its private database branch${confirmRemove?.branch ? ` (${confirmRemove.branch})` : ""}. this cannot be undone.`}
        confirmLabel="remove"
        onConfirm={() => confirmRemove && void handleRemove(confirmRemove)}
        onCancel={() => setConfirmRemove(null)}
      />
    </div>
  );
}
