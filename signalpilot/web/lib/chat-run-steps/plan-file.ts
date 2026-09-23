import type { StandaloneChatEvent } from "~/lib/api";
import { asRecord, text } from "./payload";
import { normalizeToolName } from "./tool-names";
import type { PlanItem, RunPlan } from "./types";

/**
 * The run plan kept as a markdown file, `artifacts/plan.md`.
 *
 * Claude Code 2.1.280 has no TodoWrite tool, so the agent writes its plan as
 * a GitHub task list and updates it with Write / Edit:
 *
 *     # Plan: Q3 revenue by region
 *     - [x] Load the dbt workflow
 *     - [ ] Query revenue by region
 *
 * The dock rebuilds the file from those tool events (Write sets the content,
 * Edit and MultiEdit apply their replacements, failed calls are skipped), so
 * it stays a pure function of the event stream: refresh, replay, share pages
 * and the fixture harness all derive the same plan with no file fetch.
 */

export const PLAN_FILE_PATH = "artifacts/plan.md";
const PLAN_FILE_TOOLS = new Set(["Write", "Edit", "MultiEdit"]);
const TASK_LINE = /^\s*[-*+]\s+\[([ xX])\]\s+(.+?)\s*$/;
const HEADING = /^\s*#{1,6}\s+(.+?)\s*$/;

/** True for `.../artifacts/plan.md` in any path style. */
export function isPlanFilePath(path: unknown): boolean {
  if (typeof path !== "string" || !path) return false;
  const parts = path.replace(/\\/g, "/").replace(/\/+$/, "").split("/");
  return (
    parts.length >= 2 &&
    parts[parts.length - 2] === "artifacts" &&
    parts[parts.length - 1] === "plan.md"
  );
}

type Replacement = { from: string; to: string; all: boolean };

function replacementsOf(tool: string, input: Record<string, unknown>): Replacement[] {
  const one = (edit: Record<string, unknown> | null): Replacement | null => {
    const from = typeof edit?.old_string === "string" ? edit.old_string : null;
    const to = typeof edit?.new_string === "string" ? edit.new_string : null;
    return from !== null && to !== null
      ? { from, to, all: edit?.replace_all === true }
      : null;
  };
  if (tool === "Edit") {
    const edit = one(input);
    return edit ? [edit] : [];
  }
  const edits = Array.isArray(input.edits) ? input.edits : [];
  return edits
    .map((edit) => one(asRecord(edit)))
    .filter((edit): edit is Replacement => edit !== null);
}

function applyReplacement(content: string, edit: Replacement): string {
  if (!edit.from) return content;
  return edit.all
    ? content.split(edit.from).join(edit.to)
    : content.replace(edit.from, () => edit.to);
}

/**
 * The plan file's content after the last successful write, plus the sequence
 * of the latest plan-file call in `runId`. Null when that run never touched
 * the file. Earlier runs are replayed too, so an Edit-only follow-up run
 * still has the content it edits.
 */
export function replayPlanFile(
  events: StandaloneChatEvent[],
  runId: string,
): { content: string; sequence: number } | null {
  const failed = new Set<string>();
  for (const event of events) {
    if (event.type !== "tool_completed" || event.payload.error !== true) continue;
    const id = text(event.payload.tool_call_id);
    if (id) failed.add(id);
  }
  let content: string | null = null;
  let sequence: number | null = null;
  for (const event of events) {
    if (event.type !== "tool_started") continue;
    if (text(event.payload.parent_tool_call_id)) continue;
    const rawTool = text(event.payload.tool);
    const tool = rawTool ? normalizeToolName(rawTool).tool : null;
    if (!tool || !PLAN_FILE_TOOLS.has(tool)) continue;
    const input = asRecord(event.payload.input);
    if (!input || !isPlanFilePath(input.file_path)) continue;
    const id = text(event.payload.tool_call_id);
    if (id && failed.has(id)) continue;
    if (tool === "Write") {
      if (typeof input.content !== "string") continue;
      content = input.content;
    } else if (content !== null) {
      for (const edit of replacementsOf(tool, input)) {
        content = applyReplacement(content, edit);
      }
    } else {
      continue;
    }
    if (event.run_id === runId) {
      sequence = Math.max(sequence ?? event.sequence, event.sequence);
    }
  }
  return content !== null && sequence !== null ? { content, sequence } : null;
}

/** Parse a markdown task list into plan items; the first open item is live. */
export function parsePlanMarkdown(
  markdown: string,
): { title: string | null; items: PlanItem[] } {
  let title: string | null = null;
  const items: PlanItem[] = [];
  for (const line of markdown.split(/\r?\n/)) {
    const task = TASK_LINE.exec(line);
    if (task) {
      items.push({
        content: task[2],
        activeForm: null,
        status: task[1] === " " ? "pending" : "completed",
      });
      continue;
    }
    const heading: RegExpExecArray | null =
      title === null ? HEADING.exec(line) : null;
    if (heading) title = heading[1].replace(/^plan\s*:\s*/i, "") || null;
  }
  const current = items.find((item) => item.status === "pending");
  if (current) current.status = "in_progress";
  return { title, items };
}

/** The run's plan from its plan file, or null when it wrote none. */
export function extractPlanFilePlan(
  events: StandaloneChatEvent[],
  runId: string,
): RunPlan | null {
  const replayed = replayPlanFile(events, runId);
  if (!replayed) return null;
  const { title, items } = parsePlanMarkdown(replayed.content);
  if (!items.length) return null;
  const current = items.find((item) => item.status === "in_progress") ?? null;
  return {
    items,
    completed: items.filter((item) => item.status === "completed").length,
    currentLabel: current ? current.content : null,
    sequence: replayed.sequence,
    title,
  };
}
