import type { FeedEvent, ToolCall } from "./types";
import { getToolCategory, type ToolCategory } from "./types";

/* ── Grouped Event Types ── */

export type GroupedEvent =
  | { type: "llm_message"; role: "worker" | "ceo"; text: string; thinking: string; ts: string }
  | { type: "tool_group"; category: ToolCategory; label: string; tools: ToolCall[]; ts: string; totalDuration: number }
  | { type: "agent_run"; tool: ToolCall; ts: string }
  | { type: "edit_group"; tools: ToolCall[]; ts: string; totalDuration: number }
  | { type: "bash_group"; tools: ToolCall[]; ts: string; totalDuration: number }
  | { type: "playwright_group"; tools: ToolCall[]; ts: string; totalDuration: number }
  | { type: "single_tool"; tool: ToolCall; ts: string }
  | { type: "usage_tick"; data: { input_tokens: number; output_tokens: number; total_input: number; total_output: number; cache_read: number }; ts: string }
  | { type: "control"; text: string; ts: string }
  | { type: "milestone"; label: string; detail: string; color: string; ts: string; event?: FeedEvent }
  | { type: "divider"; label: string; ts: string };

/* ── Grouping Logic ── */

const GROUPABLE_CATEGORIES = new Set<ToolCategory>(["read", "glob", "grep", "web_search", "tool_search"]);
const EDIT_CATEGORIES = new Set<ToolCategory>(["edit", "write"]);
const BASH_CATEGORY: ToolCategory = "bash";
const PLAYWRIGHT_CATEGORIES = new Set<ToolCategory>([
  "playwright_navigate", "playwright_screenshot", "playwright_snapshot",
  "playwright_click", "playwright_form", "playwright_type", "playwright_evaluate"
]);
const AGENT_CATEGORY: ToolCategory = "agent";

// Time window for grouping consecutive same-type tools (ms)
const GROUP_WINDOW = 30_000;

function getTs(e: FeedEvent): number {
  if (e._kind === "tool") return new Date(e.data.ts).getTime();
  if (e._kind === "audit") return new Date(e.data.ts).getTime();
  if (e._kind === "usage") return new Date(e.data.ts).getTime();
  return new Date(e.ts).getTime();
}

function getTsStr(e: FeedEvent): string {
  if (e._kind === "tool") return e.data.ts;
  if (e._kind === "audit") return e.data.ts;
  if (e._kind === "usage") return e.data.ts;
  return e.ts;
}

function extractFilePath(tc: ToolCall): string {
  const input = tc.input_data || {};
  const output = tc.output_data || {};
  const fp = (input.file_path as string) || (output.filePath as string) || "";
  return fp.replace(/^\/home\/agentuser\/repo\//, "").replace(/^\/workspace\//, "");
}

function milestoneFromAudit(event: FeedEvent): GroupedEvent | null {
  if (event._kind !== "audit") return null;
  const d = event.data.details;
  const ts = event.data.ts;

  switch (event.data.event_type) {
    case "run_started":
      return { type: "milestone", label: "Run Started", detail: `${d.model || "claude"} · ${d.branch || ""}`, color: "#88ccff", ts, event };
    case "round_complete":
      return { type: "divider", label: `Round ${d.round} complete · ${(d.cost_usd as number)?.toFixed(3) || "?"} USD · ${d.turns} turns`, ts };
    case "pr_created":
      return { type: "milestone", label: "PR Created", detail: String(d.url || ""), color: "#00ff88", ts, event };
    case "pr_failed":
      return { type: "milestone", label: "PR Failed", detail: String(d.error || "").slice(0, 100), color: "#ff4444", ts, event };
    case "session_ended":
      return { type: "milestone", label: "Session Ended", detail: `${d.changes_made || 0} changes · ${(d.elapsed_minutes as number)?.toFixed(1) || "?"}min`, color: "#88ccff", ts, event };
    case "killed":
      return { type: "milestone", label: "Killed", detail: `after ${(d.elapsed_minutes as number)?.toFixed(1) || "?"}min`, color: "#ff4444", ts, event };
    case "fatal_error":
      return { type: "milestone", label: "Fatal Error", detail: String(d.error || "").slice(0, 100), color: "#ff4444", ts, event };
    case "ceo_continuation":
      return { type: "milestone", label: "CEO Continuation", detail: `Round ${d.round} · ${d.tool_summary || ""}`, color: "#ff8844", ts, event };
    case "worker_assignment":
      return { type: "llm_message", role: "ceo", text: String(d.assignment || ""), thinking: "", ts };
    case "end_session_denied":
      return { type: "milestone", label: "Session Denied", detail: `${d.time_remaining || "?"} remaining`, color: "#ffaa00", ts, event };
    case "session_unlocked":
      return { type: "milestone", label: "Session Unlocked", detail: "", color: "#00ff88", ts, event };
    case "stop_requested":
      return { type: "milestone", label: "Stop Requested", detail: String(d.reason || ""), color: "#ff8844", ts, event };
    case "rate_limit_paused":
      return { type: "milestone", label: "Rate Limited", detail: `wait ${d.wait_seconds || "?"}s`, color: "#ffaa00", ts, event };
    case "sdk_config":
      return null; // Too noisy, skip
    case "rate_limit":
      return null; // Skip unless it's a problem
    default:
      return null;
  }
}

export function groupEvents(events: FeedEvent[]): GroupedEvent[] {
  const result: GroupedEvent[] = [];
  let i = 0;

  while (i < events.length) {
    const ev = events[i];

    // ── LLM Text: Accumulate consecutive same-role text + thinking ──
    if (ev._kind === "llm_text" || ev._kind === "llm_thinking") {
      let text = "";
      let thinking = "";
      const role = ev.agent_role || "worker";
      const ts = ev.ts;

      while (i < events.length) {
        const cur = events[i];
        if (cur._kind === "llm_text" && (cur.agent_role || "worker") === role) {
          text += cur.text;
          i++;
        } else if (cur._kind === "llm_thinking" && (cur.agent_role || "worker") === role) {
          thinking += cur.text;
          i++;
        } else {
          break;
        }
      }

      if (text || thinking) {
        result.push({ type: "llm_message", role, text, thinking, ts });
      }
      continue;
    }

    // ── Usage: Collapse into a single tick (take the last one in a burst) ──
    if (ev._kind === "usage") {
      let lastUsage = ev.data;
      i++;
      while (i < events.length && events[i]._kind === "usage") {
        lastUsage = (events[i] as { _kind: "usage"; data: typeof lastUsage }).data;
        i++;
      }
      result.push({
        type: "usage_tick",
        data: {
          input_tokens: lastUsage.input_tokens,
          output_tokens: lastUsage.output_tokens,
          total_input: lastUsage.total_input_tokens,
          total_output: lastUsage.total_output_tokens,
          cache_read: lastUsage.cache_read_input_tokens,
        },
        ts: lastUsage.ts,
      });
      continue;
    }

    // ── Control events ──
    if (ev._kind === "control") {
      result.push({ type: "control", text: ev.text, ts: ev.ts });
      i++;
      continue;
    }

    // ── Audit events → milestones or skip ──
    if (ev._kind === "audit") {
      const milestone = milestoneFromAudit(ev);
      if (milestone) result.push(milestone);
      i++;
      continue;
    }

    // ── Tool calls: Group by category ──
    if (ev._kind === "tool") {
      const tc = ev.data;
      const cat = getToolCategory(tc.tool_name);
      const tsMs = getTs(ev);

      // Agent calls are always standalone
      if (cat === AGENT_CATEGORY) {
        result.push({ type: "agent_run", tool: tc, ts: tc.ts });
        i++;
        continue;
      }

      // Session gate is a milestone
      if (cat === "session_gate") {
        result.push({ type: "milestone", label: "End Session", detail: "", color: "#ffffff", ts: tc.ts });
        i++;
        continue;
      }

      // Collect consecutive same-category tools
      const batch: ToolCall[] = [tc];
      i++;

      // For groupable categories (reads, globs, greps, searches)
      if (GROUPABLE_CATEGORIES.has(cat)) {
        while (i < events.length) {
          const next = events[i];
          if (next._kind !== "tool") break;
          const nextCat = getToolCategory(next.data.tool_name);
          if (nextCat !== cat) break;
          if (Math.abs(new Date(next.data.ts).getTime() - tsMs) > GROUP_WINDOW) break;
          batch.push(next.data);
          i++;
        }

        if (batch.length === 1) {
          result.push({ type: "single_tool", tool: batch[0], ts: batch[0].ts });
        } else {
          const label = cat === "read"
            ? `Read ${batch.length} files`
            : cat === "glob"
              ? `Searched ${batch.length} patterns`
              : cat === "grep"
                ? `Grep ${batch.length} searches`
                : `${batch.length} ${cat} calls`;
          const totalDuration = batch.reduce((sum, t) => sum + (t.duration_ms || 0), 0);
          result.push({ type: "tool_group", category: cat, label, tools: batch, ts: batch[0].ts, totalDuration });
        }
        continue;
      }

      // Edit/Write groups
      if (EDIT_CATEGORIES.has(cat)) {
        while (i < events.length) {
          const next = events[i];
          if (next._kind !== "tool") break;
          const nextCat = getToolCategory(next.data.tool_name);
          if (!EDIT_CATEGORIES.has(nextCat)) break;
          if (Math.abs(new Date(next.data.ts).getTime() - tsMs) > GROUP_WINDOW) break;
          batch.push(next.data);
          i++;
        }

        if (batch.length === 1) {
          result.push({ type: "single_tool", tool: batch[0], ts: batch[0].ts });
        } else {
          const totalDuration = batch.reduce((sum, t) => sum + (t.duration_ms || 0), 0);
          result.push({ type: "edit_group", tools: batch, ts: batch[0].ts, totalDuration });
        }
        continue;
      }

      // Bash groups
      if (cat === BASH_CATEGORY) {
        while (i < events.length) {
          const next = events[i];
          if (next._kind !== "tool") break;
          if (getToolCategory(next.data.tool_name) !== BASH_CATEGORY) break;
          if (Math.abs(new Date(next.data.ts).getTime() - tsMs) > GROUP_WINDOW) break;
          batch.push(next.data);
          i++;
        }

        if (batch.length === 1) {
          result.push({ type: "single_tool", tool: batch[0], ts: batch[0].ts });
        } else {
          const totalDuration = batch.reduce((sum, t) => sum + (t.duration_ms || 0), 0);
          result.push({ type: "bash_group", tools: batch, ts: batch[0].ts, totalDuration });
        }
        continue;
      }

      // Playwright groups
      if (PLAYWRIGHT_CATEGORIES.has(cat)) {
        while (i < events.length) {
          const next = events[i];
          if (next._kind !== "tool") break;
          if (!PLAYWRIGHT_CATEGORIES.has(getToolCategory(next.data.tool_name))) break;
          if (Math.abs(new Date(next.data.ts).getTime() - tsMs) > GROUP_WINDOW) break;
          batch.push(next.data);
          i++;
        }

        if (batch.length === 1) {
          result.push({ type: "single_tool", tool: batch[0], ts: batch[0].ts });
        } else {
          const totalDuration = batch.reduce((sum, t) => sum + (t.duration_ms || 0), 0);
          result.push({ type: "playwright_group", tools: batch, ts: batch[0].ts, totalDuration });
        }
        continue;
      }

      // Everything else: single tool
      result.push({ type: "single_tool", tool: tc, ts: tc.ts });
      continue;
    }

    // Fallback: skip unknown
    i++;
  }

  return result;
}

/* ── Helpers for rendering ── */

export function extractReadFiles(tools: ToolCall[]): string[] {
  return tools.map(tc => {
    const fp = extractFilePath(tc);
    return fp.split("/").pop() || fp;
  });
}

export function extractReadPaths(tools: ToolCall[]): string[] {
  return tools.map(tc => extractFilePath(tc));
}

export function extractEditSummary(tools: ToolCall[]): Array<{ file: string; path: string; added: number; removed: number }> {
  return tools.map(tc => {
    const path = extractFilePath(tc);
    const file = path.split("/").pop() || path;
    const patch = tc.output_data?.structuredPatch as Array<Record<string, unknown>> | undefined;
    let added = 0, removed = 0;
    if (patch) {
      for (const hunk of patch) {
        const lines = (hunk.lines as string[]) || [];
        for (const l of lines) {
          if (l.startsWith("+") && !l.startsWith("+++")) added++;
          if (l.startsWith("-") && !l.startsWith("---")) removed++;
        }
      }
    }
    return { file, path, added, removed };
  });
}

export function extractBashCommands(tools: ToolCall[]): Array<{ cmd: string; desc: string; output: string; exitOk: boolean; duration: number }> {
  return tools.map(tc => {
    const input = tc.input_data || {};
    const output = tc.output_data || {};
    const cmd = (input.command as string) || "";
    const desc = (input.description as string) || "";
    const stdout = (output.stdout as string) || "";
    const stderr = (output.stderr as string) || "";
    return {
      cmd: desc || cmd.slice(0, 120),
      desc,
      output: stderr ? `[stderr] ${stderr}\n${stdout}` : stdout,
      exitOk: !stderr,
      duration: tc.duration_ms || 0,
    };
  });
}
