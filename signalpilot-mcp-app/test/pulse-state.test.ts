import { derivePulse, mergeEvents } from "../src/pulse-state";
import type { RunEvent, View } from "../src/types";

let sequence = 0;
const stamp = (offset: number) => new Date(1_700_000_000_000 + offset * 1000).toISOString();
const ev = (type: string, payload: Record<string, unknown>, offset = sequence): RunEvent => ({
  run_id: "run-1",
  sequence: ++sequence,
  type,
  payload,
  created_at: stamp(offset),
});

function view(events: RunEvent[], overrides: Partial<View> = {}): View {
  return {
    thread_id: "thread-1",
    run_id: "run-1",
    chat_url: "https://app.signalpilot.ai/chats/thread-1",
    status: "running",
    events,
    messages: [],
    next_sequence: events.length,
    next_message_sequence: 0,
    has_more: false,
    has_more_messages: false,
    received_at: Date.now(),
    ...overrides,
  };
}

beforeEach(() => {
  sequence = 0;
});

describe("derivePulse", () => {
  it("starts in thinking with the queued line before any event", () => {
    const state = derivePulse(view([], { status: "queued" }));
    expect(state.phase).toBe("thinking");
    expect(state.now).toBe("Picking up your question");
    expect(state.chips).toEqual([]);
    expect(state.startedAt).toBeNull();
  });

  it("boots until the runtime is ready", () => {
    const events = [ev("runtime_boot", { phase: "provisioning", label: "Starting secure runtime" })];
    expect(derivePulse(view(events)).phase).toBe("booting");
    events.push(ev("runtime_boot", { phase: "ready" }));
    expect(derivePulse(view(events)).phase).toBe("thinking");
  });

  it("shows the running tool with its description as the Now line", () => {
    const events = [
      ev("tool_started", { tool: "mcp__signalpilot__query_database", tool_call_id: "c1", label: "Checking the date range of rpt_daily_profitability" }),
    ];
    const state = derivePulse(view(events));
    expect(state.phase).toBe("tool");
    expect(state.now).toBe("Checking the date range of rpt_daily_profitability");
    expect(state.chips[0]).toMatchObject({ kind: "table", status: "running", label: "Checking the date range of…" });
  });

  it("completes chips by tool_call_id, parses stats and plan progress", () => {
    const events = [
      ev("tool_started", { tool: "TodoWrite", tool_call_id: "p1" }),
      ev("tool_completed", { tool: "TodoWrite", tool_call_id: "p1", summary: "Plan updated · 2/5 done" }),
      ev("tool_started", { tool: "mcp__signalpilot__query_database", tool_call_id: "c1" }),
      ev("tool_started", { tool: "mcp__signalpilot__list_tables", tool_call_id: "c2" }),
      ev("tool_completed", { tool: "mcp__signalpilot__query_database", tool_call_id: "c1", summary: "1,204 rows · 0.4 s" }),
    ];
    const state = derivePulse(view(events));
    expect(state.plan).toEqual({ done: 2, total: 5 });
    expect(state.chips.map((chip) => chip.status)).toEqual(["done", "done", "running"]);
    expect(state.chips[1]?.stat).toBe("1,204 rows · 0.4 s");
    expect(state.chips[0]?.stat).toBe("2/5 done");
    expect(state.counts).toMatchObject({ queries: 2, rows: 1204, tools: 3, errors: 0 });
    expect(state.phase).toBe("tool");
    expect(state.now).toBe("Listing tables");
  });

  it("ignores subagent events for chips and thoughts", () => {
    const events = [
      ev("tool_started", { tool: "Agent", tool_call_id: "a1" }),
      ev("tool_started", { tool: "Read", tool_call_id: "r1", parent_tool_call_id: "a1" }),
      ev("text_delta", { delta: "Inner narration that should stay hidden.", parent_tool_call_id: "a1" }),
    ];
    const state = derivePulse(view(events));
    expect(state.chips).toHaveLength(1);
    expect(state.chips[0]?.kind).toBe("subagent");
    expect(state.thoughts).toEqual([]);
  });

  it("keeps the last three thoughts and marks writing after text", () => {
    const events = [
      ev("thinking_delta", { delta: "First thought here. Second thought here. " }),
      ev("tool_started", { tool: "validate_sql", tool_call_id: "v1" }),
      ev("tool_completed", { tool: "validate_sql", tool_call_id: "v1", summary: "No issues" }),
      ev("text_delta", { delta: "Third sentence lands. Fourth sentence is the newest" }),
    ];
    const state = derivePulse(view(events));
    expect(state.phase).toBe("writing");
    expect(state.thoughts.map((thought) => thought.text)).toEqual(["Second thought here.", "Third sentence lands.", "Fourth sentence is the newest"]);
    expect(state.thoughts.map((thought) => thought.id)).toEqual([1, 2, 3]);
  });

  it("returns to thinking after the last tool completes", () => {
    const events = [
      ev("tool_started", { tool: "validate_sql", tool_call_id: "v1" }),
      ev("tool_completed", { tool: "validate_sql", tool_call_id: "v1", summary: "No issues" }),
    ];
    expect(derivePulse(view(events)).phase).toBe("thinking");
  });

  it("uses the final assistant message as the completed headline", () => {
    const events = [ev("text_delta", { delta: "## Result\n\nQ3 gross margin was **37.8%**, up two points." })];
    const state = derivePulse(
      view(events, {
        status: "completed",
        messages: [{ id: "m1", role: "assistant", content: "# Q3 margin\n\nQ3 gross margin was 37.8%, up two points. More.", run_id: "run-1", sequence: 2 }],
      }),
    );
    expect(state.phase).toBe("completed");
    expect(state.now).toBe("Q3 gross margin was 37.8%, up two points.");
    expect(state.endedAt).toBe(events[0]?.created_at);
  });

  it("surfaces failures with sanitized detail and a failed chip", () => {
    const events = [
      ev("tool_started", { tool: "query_database", tool_call_id: "c1" }),
      ev("tool_completed", { tool: "query_database", tool_call_id: "c1", error: "Query timed out after 300 s" }),
      ev("error", { message: "Query timed out after 300 s on fct_refunds", raw_error: "QueryTimeout: statement exceeded 300 s" }),
    ];
    const state = derivePulse(view(events, { status: "failed", error: "Query timed out after 300 s on fct_refunds" }));
    expect(state.phase).toBe("failed");
    expect(state.now).toBe("Query timed out after 300 s on fct_refunds");
    expect(state.errorDetail).toContain("QueryTimeout");
    expect(state.chips[0]).toMatchObject({ status: "failed", stat: "Query timed out after 3…" });
    expect(state.counts.errors).toBe(1);
  });

  it("waits with the clarification question", () => {
    const events = [ev("clarification_requested", { question: "Invoice date or booking date?" })];
    const state = derivePulse(view(events, { status: "input_required" }));
    expect(state.phase).toBe("waiting");
    expect(state.question).toBe("Invoice date or booking date?");
  });

  it("keeps the latest plan steps and derives progress from them", () => {
    const events = [
      ev("tool_started", { tool: "TodoWrite", tool_call_id: "p1", plan: [
        { content: "Scan project", status: "completed", active: "Scanning project" },
        { content: "Build mart", status: "in_progress", active: "Building mart" },
        { content: "Verify", status: "pending" },
        { content: "", status: "pending" },
        { content: "Odd", status: "nope" },
      ] }),
      ev("tool_completed", { tool: "TodoWrite", tool_call_id: "p1", summary: "Plan updated · 9/9 done" }),
    ];
    const state = derivePulse(view(events));
    expect(state.planItems.map((item) => [item.content, item.status, item.active])).toEqual([
      ["Scan project", "completed", "Scanning project"],
      ["Build mart", "in_progress", "Building mart"],
      ["Verify", "pending", null],
      ["Odd", "pending", null],
    ]);
    expect(state.plan).toEqual({ done: 1, total: 4 });
  });

  it("closes calls left open by runtime recovery", () => {
    const events = [
      ev("tool_started", { tool: "Agent", tool_call_id: "a1" }),
      ev("tool_started", { tool: "Read", tool_call_id: "r1", parent_tool_call_id: "a1" }),
      ev("status", { status: "running", reset_text: true }),
      ev("tool_started", { tool: "query_database", tool_call_id: "q1" }),
    ];
    const state = derivePulse(view(events));
    expect(state.chips.map((chip) => [chip.status, chip.stat])).toEqual([["done", "interrupted"], ["running", ""]]);
    expect(state.now).toBe("Querying the warehouse");
  });

  it("clears streamed text when the status event asks for a reset", () => {
    const events = [ev("text_delta", { delta: "Old narration that was superseded." }), ev("status", { status: "running", reset_text: true })];
    expect(derivePulse(view(events)).thoughts).toEqual([]);
  });
});

describe("mergeEvents", () => {
  it("deduplicates by sequence and keeps order", () => {
    const a = ev("progress", { label: "a" });
    const b = ev("progress", { label: "b" });
    const merged = mergeEvents([b], [a, { ...b, payload: { label: "b2" } }]);
    expect(merged.map((event) => event.sequence)).toEqual([a.sequence, b.sequence]);
    expect(merged[1]?.payload.label).toBe("b2");
  });
});
