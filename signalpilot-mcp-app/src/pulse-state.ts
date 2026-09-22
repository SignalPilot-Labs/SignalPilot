import { headlineFrom, recentThoughts } from "./thoughts";
import {
  chipStat,
  kindForTool,
  normalizeToolName,
  nounForKind,
  parsePlan,
  parseRows,
  presentLabel,
  shortLabel,
} from "./tool-meta";
import type { Chip, Counts, Phase, Plan, PlanItem, PulseState, RunEvent, View } from "./types";

/**
 * Pure projection of a view page into what the panel shows. Deterministic
 * over the event list, so replaying the same page yields the same frame.
 */

const text = (value: unknown): string | null => (typeof value === "string" && value.length > 0 ? value : null);

const EMPTY_COUNTS: Counts = { queries: 0, checks: 0, files: 0, errors: 0, tools: 0, rows: 0 };

function countChips(chips: Chip[]): Counts {
  const counts = { ...EMPTY_COUNTS, tools: chips.length };
  for (const chip of chips) {
    if (chip.kind === "table" || chip.kind === "table_list" || chip.kind === "schema") counts.queries += 1;
    if (chip.kind === "validation" || chip.kind === "dbt_run") counts.checks += 1;
    if (chip.kind === "file") counts.files += 1;
    if (chip.status === "failed") counts.errors += 1;
    const rows = parseRows(chip.stat);
    if (rows !== null) counts.rows += rows;
  }
  return counts;
}

type Trailing = "none" | "text" | "thinking" | "tool" | "tool_done";

const PLAN_STATUSES = new Set(["pending", "in_progress", "completed"]);

/** Display-safe plan steps as projected by the gateway; anything odd is dropped. */
export function parsePlanItems(value: unknown): PlanItem[] {
  if (!Array.isArray(value)) return [];
  const items: PlanItem[] = [];
  for (const raw of value) {
    if (!raw || typeof raw !== "object") continue;
    const item = raw as Record<string, unknown>;
    const content = text(item.content)?.trim();
    if (!content) continue;
    const status = text(item.status);
    items.push({
      content,
      status: status && PLAN_STATUSES.has(status) ? (status as PlanItem["status"]) : "pending",
      active: text(item.active)?.trim() || null,
    });
  }
  return items;
}

export function derivePulse(view: View): PulseState {
  const events = view.events
    .filter((event) => event.run_id === view.run_id)
    .sort((a, b) => a.sequence - b.sequence);
  const chips: Chip[] = [];
  const open = new Map<string, Chip>();
  let stream = "";
  let bootReady = events.length === 0 || !events.some((event) => event.type === "runtime_boot");
  let bootLabel = "Starting secure runtime";
  let plan: Plan | null = null;
  let planItems: PlanItem[] = [];
  let trailing: Trailing = "none";
  let question: string | null = null;
  let error: string | null = null;
  let errorDetail: string | null = null;
  let progress: string | null = null;

  for (const event of events) {
    const payload = event.payload ?? {};
    const parent = text(payload.parent_tool_call_id);
    switch (event.type) {
      case "runtime_boot": {
        const phase = text(payload.phase);
        if (phase === "ready") bootReady = true;
        else {
          bootReady = false;
          bootLabel = text(payload.label) ?? (phase === "resuming" ? "Resuming the warehouse sandbox" : "Starting secure runtime");
        }
        break;
      }
      case "status":
        if (payload.reset_text === true) {
          // Runtime recovery: the previous attempt's open calls can never
          // report back, so close them here even on older event streams.
          stream = "";
          for (const chip of open.values()) {
            chip.status = "done";
            chip.stat = "interrupted";
            chip.endedAt = event.created_at;
          }
          open.clear();
          trailing = "none";
        }
        break;
      case "text_delta":
        if (parent) break;
        stream += text(payload.delta) ?? "";
        trailing = "text";
        break;
      case "thinking_delta":
        if (parent) break;
        stream += text(payload.delta) ?? "";
        trailing = "thinking";
        break;
      case "progress":
        progress = text(payload.label);
        break;
      case "tool_started": {
        if (parent) break;
        const tool = normalizeToolName(text(payload.tool) ?? "tool");
        const kind = kindForTool(tool);
        const label = text(payload.label);
        const chip: Chip = {
          id: text(payload.tool_call_id) ?? `seq-${event.sequence}`,
          kind,
          tool,
          label: label ? shortLabel(label) : nounForKind(kind),
          detail: label ?? presentLabel(tool),
          stat: "",
          status: "running",
          startedAt: event.created_at,
          endedAt: null,
        };
        chips.push(chip);
        open.set(chip.id, chip);
        if (kind === "plan") {
          const items = parsePlanItems(payload.plan);
          if (items.length) {
            planItems = items;
            plan = { done: items.filter((item) => item.status === "completed").length, total: items.length };
          }
        }
        trailing = "tool";
        progress = null;
        break;
      }
      case "tool_completed": {
        if (parent) break;
        const id = text(payload.tool_call_id);
        const chip = (id && open.get(id)) || [...open.values()].at(-1);
        if (!chip) break;
        open.delete(chip.id);
        const summary = text(payload.summary);
        const failed = Boolean(payload.error);
        chip.status = failed ? "failed" : "done";
        chip.endedAt = event.created_at;
        const planUpdate = chip.kind === "plan" && summary ? parsePlan(summary) : null;
        if (planUpdate && !planItems.length) plan = planUpdate;
        chip.stat = failed
          ? chipStat(text(payload.error) ?? "failed")
          : planUpdate
            ? `${planUpdate.done}/${planUpdate.total} done`
            : chipStat(summary);
        if (open.size === 0) trailing = "tool_done";
        break;
      }
      case "clarification_requested":
      case "query_approval_requested":
        question = text(payload.question) ?? text(payload.message);
        break;
      case "error": {
        error = text(payload.message) ?? text(payload.error) ?? error;
        const parts = [payload.raw_error, payload.stderr, payload.full_trace].filter(
          (part): part is string => typeof part === "string" && part.trim().length > 0,
        );
        if (parts.length) errorDetail = [...new Set(parts)].join("\n");
        break;
      }
      default:
        break;
    }
  }

  const finalMessage = view.messages
    .filter((message) => message.role === "assistant" && message.run_id === view.run_id)
    .sort((a, b) => a.sequence - b.sequence)
    .at(-1);
  const headline = headlineFrom(finalMessage?.content ?? stream);
  const running = open.size > 0 ? [...open.values()].at(-1)! : null;
  const status = view.status;
  const viewError = text(view.error) ?? error;
  const viewDetail = [view.raw_error, view.stderr, view.full_trace].filter(
    (part): part is string => typeof part === "string" && part.trim().length > 0,
  );

  let phase: Phase;
  let now: string;
  if (status === "completed") {
    phase = "completed";
    now = headline ?? "Finished";
  } else if (status === "failed") {
    phase = "failed";
    now = viewError ?? "The run stopped";
  } else if (status === "cancelled") {
    phase = "cancelled";
    now = "Cancelled";
  } else if (status === "input_required") {
    phase = "waiting";
    now = "SignalPilot has a question";
  } else if (!bootReady) {
    phase = "booting";
    now = bootLabel;
  } else if (running) {
    phase = "tool";
    now = running.detail;
  } else if (trailing === "text") {
    phase = "writing";
    now = "Writing the answer";
  } else {
    phase = "thinking";
    now = progress ?? (status === "queued" && events.length === 0 ? "Picking up your question" : "Thinking");
  }

  return {
    phase,
    now,
    thoughts: recentThoughts(stream),
    chips,
    plan,
    planItems,
    counts: countChips(chips),
    question: text(view.question) ?? question,
    error: viewError,
    errorDetail: viewDetail.length ? [...new Set(viewDetail)].join("\n") : errorDetail,
    headline,
    chatUrl: view.chat_url,
    startedAt: events[0]?.created_at ?? null,
    endedAt: phase === "completed" || phase === "failed" || phase === "cancelled" ? (events.at(-1)?.created_at ?? null) : null,
  };
}

/** Merge a page of events into the known list, deduplicated by sequence. */
export function mergeEvents(existing: RunEvent[], incoming: RunEvent[]): RunEvent[] {
  if (!incoming.length) return existing;
  const bySequence = new Map(existing.map((event) => [event.sequence, event]));
  for (const event of incoming) bySequence.set(event.sequence, event);
  return [...bySequence.values()].sort((a, b) => a.sequence - b.sequence);
}
