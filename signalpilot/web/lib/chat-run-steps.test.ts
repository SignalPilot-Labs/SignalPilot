import { describe, expect, it } from "vitest";
import {
  activeDashboardAuthoringProgress,
  activeDashboardPreviewLabel,
  extractRunPlan,
  extractRuntimeBoot,
  foldRunBlocks,
  foldRunSteps,
  formatErrorSupportBundle,
  formatStepDuration,
  normalizeToolName,
  shouldShowAgentThinking,
  shouldShowRuntimeBoot,
  summarizeRunSteps,
} from "~/lib/chat-run-steps";
import {
  FIXTURE_RUN_ID,
  FIXTURE_TOTAL_MS,
  materializeFixtureEvents,
} from "~/lib/chat-test-fixture";

const allEvents = materializeFixtureEvents(FIXTURE_TOTAL_MS);

describe("normalizeToolName", () => {
  it("strips MCP prefixes and classifies the origin", () => {
    expect(normalizeToolName("mcp__signalpilot__query_database")).toEqual({
      tool: "query_database",
      origin: "signalpilot",
    });
    expect(normalizeToolName("mcp__signalpilot-notebook__run_cells")).toEqual({
      tool: "run_cells",
      origin: "notebook",
    });
    expect(normalizeToolName("Bash")).toEqual({
      tool: "Bash",
      origin: "claude-code",
    });
  });
});

describe("foldRunSteps", () => {
  const steps = foldRunSteps(allEvents, FIXTURE_RUN_ID);

  it("pairs tool starts with completions in order", () => {
    expect(steps.every((step) => step.status !== "running")).toBe(true);
    const validate = steps.find((step) => step.tool === "validate_sql");
    expect(validate?.status).toBe("failed");
    expect(validate?.sql).toContain("region_name");
    expect(validate?.detail).toContain("does not exist");
    const query = steps.find((step) => step.tool === "query_database");
    expect(query?.status).toBe("succeeded");
    expect(query?.durationMs).toBeGreaterThan(2_000);
  });

  it("extracts code and file paths from base Claude Code tools", () => {
    const write = steps.find((step) => step.tool === "Write");
    expect(write?.category).toBe("file-write");
    expect(write?.file).toBe("analysis/q3_growth.py");
    expect(write?.code).toContain("def growth");
    const bash = steps.find((step) => step.tool === "Bash");
    expect(bash?.category).toBe("terminal");
    expect(bash?.code).toContain("python analysis/q3_growth.py");
    const edit = steps.find((step) => step.tool === "Edit");
    expect(edit?.category).toBe("file-edit");
    expect(edit?.input?.new_string).toContain("all regions");
  });

  it("attaches source chips to schema tools", () => {
    const schema = steps.find((step) => step.tool === "get_table_schema");
    expect(schema?.category).toBe("source");
    expect(schema?.sources).toEqual(
      expect.arrayContaining(["analytics", "fct_orders"]),
    );
  });

  it("ignores events from other runs", () => {
    expect(foldRunSteps(allEvents, "other-run")).toEqual([]);
  });

  it("keeps the exact upstream message, trace, and safe diagnostics", () => {
    const error = foldRunSteps(
      [
        {
          run_id: "failed-run",
          sequence: 1,
          type: "error" as const,
          payload: {
            message: "You've hit your session limit · resets 2:50pm (America/Los_Angeles)",
            full_trace: "CLIConnectionError: authentication failed\n[traceback]",
            diagnostic_context: {
              auth_mode: "oauth",
              credential_present: true,
              api_error_status: 429,
              rate_limit: {
                status: "rejected",
                resets_at: 1788213000,
              },
            },
          },
          created_at: "2026-08-31T00:00:00Z",
        },
      ],
      "failed-run",
    )[0];

    expect(error.detail).toBe(
      "You've hit your session limit · resets 2:50pm (America/Los_Angeles)",
    );
    expect(error.fullTrace).toContain("[traceback]");
    expect(error.diagnostics).toEqual({
      auth_mode: "oauth",
      credential_present: true,
      api_error_status: 429,
      rate_limit: {
        status: "rejected",
        resets_at: 1788213000,
      },
    });
    expect(formatErrorSupportBundle(error)).toBe(
      "Root cause: You've hit your session limit · resets 2:50pm (America/Los_Angeles)\n\n" +
        "Diagnostics:\n" +
        "auth_mode: oauth\n" +
        "credential_present: true\n" +
        "api_error_status: 429\n" +
        'rate_limit: {"status":"rejected","resets_at":1788213000}\n\n' +
        "Full trace:\nCLIConnectionError: authentication failed\n[traceback]",
    );
  });

  it("leaves an unmatched tool start running", () => {
    const partial = foldRunSteps(
      materializeFixtureEvents(5_000),
      FIXTURE_RUN_ID,
    );
    const query = partial.find((step) => step.tool === "query_database");
    expect(query?.status).toBe("running");
  });

  it("updates one live dashboard step from real authoring phases", () => {
    const dashboardEvents = [
      {
        run_id: "dashboard-run",
        sequence: 1,
        type: "tool_started" as const,
        payload: {
          tool: "mcp__standalone-chat__create_dashboard_preview",
          tool_call_id: "dashboard-call",
          input: { request: "Build a sales dashboard", timezone: "UTC" },
        },
        created_at: "2026-09-01T10:00:00Z",
      },
      {
        run_id: "dashboard-run",
        sequence: 2,
        type: "progress" as const,
        payload: {
          scope: "dashboard_authoring",
          phase: "drafting",
          label: "Drafting the dashboard structure and charts",
        },
        created_at: "2026-09-01T10:00:01Z",
      },
      {
        run_id: "dashboard-run",
        sequence: 3,
        type: "progress" as const,
        payload: {
          scope: "dashboard_authoring",
          phase: "validating",
          label: "Validating chart fields, filters, and bindings",
        },
        created_at: "2026-09-01T10:00:02Z",
      },
    ];

    const dashboardSteps = foldRunSteps(dashboardEvents, "dashboard-run");
    expect(dashboardSteps).toHaveLength(1);
    expect(dashboardSteps[0]).toMatchObject({
      category: "dashboard",
      status: "running",
      detail: "Validating chart fields, filters, and bindings",
    });
    expect(
      activeDashboardPreviewLabel(dashboardEvents, "dashboard-run"),
    ).toBe("Validating chart fields, filters, and bindings");

    expect(
      activeDashboardPreviewLabel(
        [
          ...dashboardEvents,
          {
            run_id: "dashboard-run",
            sequence: 4,
            type: "tool_completed" as const,
            payload: { tool_call_id: "dashboard-call", error: false },
            created_at: "2026-09-01T10:00:03Z",
          },
        ],
        "dashboard-run",
      ),
    ).toBeNull();
  });

  it("exposes the plan-ready session and revision for event-driven preview refresh", () => {
    const progress = activeDashboardAuthoringProgress(
      [
        {
          run_id: "dashboard-run",
          sequence: 1,
          type: "progress" as const,
          payload: {
            scope: "dashboard_authoring",
            phase: "plan_ready",
            label: "Plan ready with 9 charts",
            authoring_session_id: "session-progressive",
            draft_revision: 4,
          },
          created_at: "2026-09-01T10:00:00Z",
        },
      ],
      "dashboard-run",
    );

    expect(progress).toEqual({
      label: "Plan ready with 9 charts",
      phase: "plan_ready",
      sessionId: "session-progressive",
      draftRevision: 4,
    });
  });

  it("normalizes governed-tool wording in persisted chat events", () => {
    const [failed] = foldRunSteps(
      [
        {
          run_id: "legacy-run",
          sequence: 1,
          type: "tool_started" as const,
          payload: {
            tool: "mcp__signalpilot__query_database",
            tool_call_id: "legacy-tool",
            input: {},
          },
          created_at: "2026-08-31T00:00:00Z",
        },
        {
          run_id: "legacy-run",
          sequence: 2,
          type: "tool_completed" as const,
          payload: {
            tool_call_id: "legacy-tool",
            summary: "The governed tool returned an error.",
            error: true,
          },
          created_at: "2026-08-31T00:00:01Z",
        },
      ],
      "legacy-run",
    );

    expect(failed.detail).toBe("The tool returned an error.");
  });

  it("groups subagent work under its spawn with an exact tally", () => {
    const spawn = steps.find((step) => step.category === "subagent");
    expect(spawn?.title).toBe("Map the revenue marts and their grain");
    expect(spawn?.subagentType).toBe("Explore");
    expect(spawn?.status).toBe("succeeded");
    expect(spawn?.children.map((child) => child.tool)).toEqual([
      "Glob",
      "Read",
      "Grep",
    ]);
    expect(spawn?.children.every((child) => child.status === "succeeded")).toBe(
      true,
    );
    expect(spawn?.report).toContain("Three marts touch");
    expect(spawn?.liveText).toContain("checking each one's grain");
    // Child tools never leak into the top-level timeline.
    expect(steps.some((step) => step.tool === "Grep")).toBe(false);
  });

  it("keeps subagent narration out of the main text blocks", () => {
    const blocks = foldRunBlocks(allEvents, FIXTURE_RUN_ID);
    const mainText = blocks
      .filter((block) => block.kind === "text")
      .map((block) => (block as { text: string }).text)
      .join("");
    expect(mainText).not.toContain("checking each one's grain");
  });
});

describe("plan and route step enrichment", () => {
  const base = { run_id: "run-p", created_at: "2026-01-01T00:00:00Z" } as const;
  const steps = foldRunSteps(
    [
      {
        ...base,
        sequence: 1,
        type: "plan_created",
        payload: {
          plan_id: "p1",
          purpose: "Rank accounts by revenue",
          sql: "select 1",
          estimated_output_rows: 120,
        },
      },
      {
        ...base,
        sequence: 2,
        type: "route_selected",
        payload: {
          plan_id: "p1",
          route: "aggregate_required",
        },
      },
    ],
    "run-p",
  );

  it("surfaces the plan purpose, SQL, and row estimate", () => {
    expect(steps[0].title).toBe("Planned a governed query (~120 rows)");
    expect(steps[0].detail).toBe("Rank accounts by revenue");
    expect(steps[0].sql).toBe("select 1");
  });

  it("shows only the actionable route", () => {
    expect(steps[1].title).toContain("needs a bounded aggregate");
    expect(steps[1].detail).toBeNull();
    expect(steps[1].input).toBeNull();
  });
});

describe("foldRunBlocks", () => {
  it("splits the run into tool chains separated by streamed narration", () => {
    const blocks = foldRunBlocks(allEvents, FIXTURE_RUN_ID);
    expect(blocks.map((block) => block.kind)).toEqual([
      "thinking",
      "steps",
      "text",
      "steps",
      "text",
    ]);
    const [thinking, chain1, narration, chain2, answer] = blocks;
    if (thinking.kind !== "thinking") throw new Error();
    if (chain1.kind !== "steps" || chain2.kind !== "steps") throw new Error();
    if (narration.kind !== "text" || answer.kind !== "text") throw new Error();
    expect(thinking.text).toContain("fct_orders looks right");
    expect(chain1.steps).toHaveLength(6); // progress → todo → schema → validate → query → subagent
    expect(chain1.steps.at(-1)?.tool).toBe("Agent");
    expect(chain1.steps.at(-2)?.tool).toBe("query_database");
    expect(narration.text).toContain("analysis runtime");
    expect(chain2.steps).toHaveLength(7); // notebook → write → bash → todo → edit → 2 publishes
    expect(chain2.steps[0]?.tool).toBe("start_analysis_notebook");
    expect(answer.text).toContain("EMEA drove the growth");
  });

  it("keeps a mid-stream narration attached to no group while the next chain runs", () => {
    const blocks = foldRunBlocks(
      materializeFixtureEvents(9_500),
      FIXTURE_RUN_ID,
    );
    expect(blocks.map((block) => block.kind)).toEqual([
      "thinking",
      "steps",
      "text",
      "steps",
    ]);
    const tail = blocks[3];
    if (tail.kind !== "steps") throw new Error();
    expect(tail.steps.some((step) => step.status === "running")).toBe(true);
  });
});

describe("shouldShowAgentThinking", () => {
  it("shows while an active run has not started its first tool", () => {
    expect(shouldShowAgentThinking([], true)).toBe(true);
  });

  it("shows after a tool chain completes while the run remains active", () => {
    const blocks = foldRunBlocks(
      materializeFixtureEvents(7_420),
      FIXTURE_RUN_ID,
    );
    expect(blocks.at(-1)?.kind).toBe("steps");
    expect(shouldShowAgentThinking(blocks, true)).toBe(true);
  });

  it("stays hidden while a tool or real thinking block is active", () => {
    const toolBlocks = foldRunBlocks(
      materializeFixtureEvents(5_000),
      FIXTURE_RUN_ID,
    );
    const thinkingBlocks = foldRunBlocks(
      materializeFixtureEvents(360),
      FIXTURE_RUN_ID,
    );
    expect(shouldShowAgentThinking(toolBlocks, true)).toBe(false);
    expect(shouldShowAgentThinking(thinkingBlocks, true)).toBe(false);
  });

  it("stays hidden after the run finishes", () => {
    expect(shouldShowAgentThinking(foldRunBlocks(allEvents, FIXTURE_RUN_ID), false)).toBe(false);
  });
});

describe("extractRuntimeBoot", () => {
  it("returns the boot lifecycle for a cold-start run", () => {
    const boot = extractRuntimeBoot(allEvents, FIXTURE_RUN_ID);
    expect(boot?.phase).toBe("ready");
    expect(boot?.bootMs).toBe(41_200);
    expect(boot?.readyAt).toBeTruthy();
  });

  it("stays in the live phase until ready arrives", () => {
    const boot = extractRuntimeBoot(
      materializeFixtureEvents(100),
      FIXTURE_RUN_ID,
    );
    expect(boot?.phase).toBe("provisioning");
    expect(boot?.readyAt).toBeNull();
  });

  it("returns null for warm runs with no boot events", () => {
    const warmEvents = allEvents.filter(
      (event) => event.type !== "runtime_boot",
    );
    expect(extractRuntimeBoot(warmEvents, FIXTURE_RUN_ID)).toBeNull();
  });

  it("hides an unresolved boot as soon as its run is terminal", () => {
    const boot = extractRuntimeBoot(
      materializeFixtureEvents(100),
      FIXTURE_RUN_ID,
    );
    expect(shouldShowRuntimeBoot(boot, true)).toBe(true);
    expect(shouldShowRuntimeBoot(boot, false)).toBe(false);
  });

  it("keeps completed boot provenance in a terminal transcript", () => {
    const boot = extractRuntimeBoot(allEvents, FIXTURE_RUN_ID);
    expect(shouldShowRuntimeBoot(boot, false)).toBe(true);
  });
});

describe("summarizeRunSteps", () => {
  it("counts queries, code runs, files and errors", () => {
    const summary = summarizeRunSteps(foldRunSteps(allEvents, FIXTURE_RUN_ID));
    expect(summary.queries).toBe(2); // validate_sql + query_database
    expect(summary.codeRuns).toBe(1); // Bash
    expect(summary.files).toBe(4); // Write + Edit + publish_table + publish_chart
    expect(summary.errors).toBe(1);
    expect(summary.running).toBe(false);
  });
});

describe("formatStepDuration", () => {
  it("formats sub-second, second and minute scales", () => {
    expect(formatStepDuration(null)).toBeNull();
    expect(formatStepDuration(40)).toBe("<0.1s");
    expect(formatStepDuration(2_600)).toBe("2.6s");
    expect(formatStepDuration(94_000)).toBe("1m 34s");
  });
});

describe("extractRunPlan", () => {
  it("returns null before any TodoWrite is published", () => {
    expect(extractRunPlan(materializeFixtureEvents(500), FIXTURE_RUN_ID)).toBeNull();
    expect(extractRunPlan(allEvents, "some-other-run")).toBeNull();
  });

  it("reads the first published plan mid-run", () => {
    const plan = extractRunPlan(materializeFixtureEvents(2_000), FIXTURE_RUN_ID);
    expect(plan).not.toBeNull();
    expect(plan!.items).toHaveLength(4);
    expect(plan!.completed).toBe(0);
    expect(plan!.currentLabel).toBe(
      "Confirm the revenue model and region join",
    );
  });

  it("tracks the latest TodoWrite as the run progresses", () => {
    const plan = extractRunPlan(allEvents, FIXTURE_RUN_ID);
    expect(plan).not.toBeNull();
    expect(plan!.completed).toBe(3);
    expect(plan!.items[3].status).toBe("in_progress");
    expect(plan!.currentLabel).toBe("Publish a table and comparison chart");
  });

  it("ignores TodoWrites published inside subagents", () => {
    const maxSequence = allEvents.reduce(
      (max, event) => Math.max(max, event.sequence),
      0,
    );
    const withSubagentPlan = [
      ...allEvents,
      {
        ...allEvents[0],
        sequence: maxSequence + 1,
        type: "tool_started" as const,
        payload: {
          tool: "TodoWrite",
          parent_tool_call_id: "toolu_subagent",
          input: { todos: [{ content: "Subagent-only step", status: "pending" }] },
        },
      },
    ];
    const plan = extractRunPlan(withSubagentPlan, FIXTURE_RUN_ID);
    expect(plan!.items.map((item) => item.content)).not.toContain(
      "Subagent-only step",
    );
  });
});
