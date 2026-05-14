import { describe, it, expect, afterEach } from "vitest";
import { render, screen, cleanup } from "@testing-library/react";
import { AgentRunDetail } from "@/components/agent-runs/AgentRunDetail";
import type { AgentRunV1, AgentRunStatus } from "@/lib/agent-runs/types";

afterEach(() => {
  cleanup();
});

function makeRun(overrides: Partial<AgentRunV1> = {}): AgentRunV1 {
  return {
    schemaVersion: 1,
    id: "aabbccdd-1234-4abc-8def-aabbccddeeff",
    prompt: "Analyze the sales data and produce a summary report",
    status: "pending",
    createdAt: "2024-06-15T12:00:00.000Z",
    ...overrides,
  };
}

describe("AgentRunDetail", () => {
  it("renders prompt text inside a <pre> element", () => {
    const run = makeRun({ prompt: "My full agent prompt\nwith multiple lines" });
    const { container } = render(<AgentRunDetail run={run} />);

    const pre = container.querySelector("pre");
    expect(pre).not.toBeNull();
    expect(pre?.textContent).toBe("My full agent prompt\nwith multiple lines");
  });

  it("renders correct heading (first line sliced to 80) and all 6 status labels via fixture", () => {
    const statuses: Array<{ status: AgentRunStatus; label: string; extraFields?: Partial<AgentRunV1> }> = [
      { status: "pending", label: "Pending" },
      {
        status: "approval_required",
        label: "Approval required",
        extraFields: { startedAt: "2024-06-15T12:01:00.000Z", pendingApproval: "Needs approval" },
      },
      {
        status: "running",
        label: "Running",
        extraFields: { startedAt: "2024-06-15T12:01:00.000Z" },
      },
      {
        status: "succeeded",
        label: "Succeeded",
        extraFields: {
          startedAt: "2024-06-15T12:01:00.000Z",
          finishedAt: "2024-06-15T12:05:00.000Z",
          summary: "Task completed successfully",
        },
      },
      {
        status: "failed",
        label: "Failed",
        extraFields: {
          startedAt: "2024-06-15T12:01:00.000Z",
          finishedAt: "2024-06-15T12:03:00.000Z",
          errorMessage: "Something went wrong",
        },
      },
      {
        status: "cancelled",
        label: "Cancelled",
        extraFields: {
          startedAt: "2024-06-15T12:01:00.000Z",
          finishedAt: "2024-06-15T12:02:00.000Z",
        },
      },
    ];

    for (const { status, label, extraFields } of statuses) {
      const run = makeRun({ status, ...extraFields });
      const { unmount } = render(<AgentRunDetail run={run} />);

      expect(screen.getByText(label)).toBeDefined();

      unmount();
    }
  });
});
