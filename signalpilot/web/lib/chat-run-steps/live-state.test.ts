import { describe, expect, it } from "vitest";
import {
  deriveLiveState,
  deriveLiveStateFromBlocks,
  foldRunBlocks,
} from "~/lib/chat-run-steps";
import {
  FIXTURE_RUN_ID,
  FIXTURE_TOTAL_MS,
  fixtureRunStatus,
  materializeFixtureEvents,
} from "~/lib/chat-test-fixture";

const liveAt = (at: number) =>
  deriveLiveState(materializeFixtureEvents(at), FIXTURE_RUN_ID, fixtureRunStatus(at));

describe("deriveLiveState on the fixture replay", () => {
  it("is booting while the sandbox provisions", () => {
    expect(liveAt(100)).toMatchObject({ state: "booting", label: "Starting secure runtime", step: null });
  });

  it("is thinking while a thinking block streams", () => {
    expect(liveAt(360)).toMatchObject({ state: "thinking", label: "Thinking" });
  });

  it("names the deepest running tool, preferring a subagent's running child", () => {
    const query = liveAt(4_800);
    expect(query.state).toBe("tool");
    expect(query.step?.tool).toBe("query_database");
    expect(query.label).toBe("Comparing Q2 and Q3 revenue by region from fct_orders");
    const child = liveAt(5_200);
    expect(child.state).toBe("tool");
    expect(child.step?.tool).toBe("Glob");
    expect(child.label).toBe("Searched for files");
  });

  it("is thinking in the quiet gap after a tool chain completes", () => {
    expect(liveAt(7_420)).toMatchObject({ state: "thinking", label: "Thinking", step: null });
  });

  it("is writing while the answer streams", () => {
    expect(liveAt(18_500)).toMatchObject({ state: "writing", label: "Writing", step: null });
  });

  it("goes idle once the run completes", () => {
    expect(liveAt(FIXTURE_TOTAL_MS)).toEqual({ state: "idle", label: "", step: null });
  });

  it("returns to tool work for the follow-up chain after the answer", () => {
    const listing = liveAt(21_300);
    expect(listing.state).toBe("tool");
    expect(listing.step?.tool).toBe("list_tables");
    expect(liveAt(21_700).state).toBe("thinking");
    const dbt = liveAt(23_000);
    expect(dbt.state).toBe("tool");
    expect(dbt.step?.tool).toBe("dbt_execute");
    expect(dbt.label).toBe("Ran dbt against the warehouse");
    expect(liveAt(24_100).state).toBe("writing");
  });
});

describe("deriveLiveState edge cases", () => {
  it("picks up a queued run with no events yet", () => {
    expect(deriveLiveState([], "run-x", "queued")).toMatchObject({
      state: "thinking",
      label: "Picking up your question",
    });
    expect(deriveLiveState([], "run-x", "running").label).toBe("Thinking");
  });

  it("is idle without a run id or on a terminal status", () => {
    const events = materializeFixtureEvents(5_000);
    expect(deriveLiveState(events, undefined, "running").state).toBe("idle");
    expect(deriveLiveState(events, FIXTURE_RUN_ID, "failed").state).toBe("idle");
    expect(deriveLiveState(events, FIXTURE_RUN_ID, "waiting_for_user").state).toBe("idle");
  });

  it("uses the running step's detail as the label when present", () => {
    const blocks = foldRunBlocks(materializeFixtureEvents(5_000), FIXTURE_RUN_ID);
    const live = deriveLiveStateFromBlocks(blocks, null, "running");
    expect(live.state).toBe("tool");
    expect(live.step).not.toBeNull();
    if (live.step) {
      live.step.detail = "Scanning the warehouse";
      expect(deriveLiveStateFromBlocks(blocks, null, "running").label).toBe("Scanning the warehouse");
    }
  });
});
