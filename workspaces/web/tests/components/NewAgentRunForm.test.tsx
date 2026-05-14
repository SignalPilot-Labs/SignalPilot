import React from "react";
import { describe, it, expect, vi, afterEach } from "vitest";
import { render, screen, cleanup, fireEvent, waitFor } from "@testing-library/react";

afterEach(() => {
  cleanup();
  vi.resetModules();
});

// Mock next/navigation
const mockPush = vi.fn();
vi.mock("next/navigation", () => ({
  useRouter: () => ({ push: mockPush }),
}));

// Mock the server action
const mockSaveAgentRun = vi.fn();
vi.mock("@/lib/agent-runs/save-run", () => ({
  saveAgentRun: mockSaveAgentRun,
}));

describe("NewAgentRunForm", () => {
  it("shows 'Prompt is required.' on client when prompt is empty", async () => {
    const { NewAgentRunForm } = await import("@/components/agent-runs/NewAgentRunForm");
    render(<NewAgentRunForm />);

    const form = screen.getByRole("button", { name: "Start run" }).closest("form")!;
    fireEvent.submit(form);

    await waitFor(() => {
      expect(screen.getByRole("alert")).toBeDefined();
      expect(screen.getByText("Prompt is required.")).toBeDefined();
    });

    expect(mockSaveAgentRun).not.toHaveBeenCalled();
  });

  it("shows length error on client when prompt > 4000 chars", async () => {
    const { NewAgentRunForm } = await import("@/components/agent-runs/NewAgentRunForm");
    render(<NewAgentRunForm />);

    const textarea = screen.getByLabelText("Prompt");
    fireEvent.change(textarea, { target: { value: "a".repeat(4001) } });

    const form = screen.getByRole("button", { name: "Start run" }).closest("form")!;
    fireEvent.submit(form);

    await waitFor(() => {
      expect(screen.getByText("Prompt must be 4000 characters or fewer.")).toBeDefined();
    });

    expect(mockSaveAgentRun).not.toHaveBeenCalled();
  });

  it("calls router.push with /agent-runs/<id> on ok server result", async () => {
    mockPush.mockClear();
    mockSaveAgentRun.mockResolvedValueOnce({ ok: true, id: "test-run-id-123" });

    const { NewAgentRunForm } = await import("@/components/agent-runs/NewAgentRunForm");
    render(<NewAgentRunForm />);

    const textarea = screen.getByLabelText("Prompt");
    fireEvent.change(textarea, { target: { value: "Analyze the sales data" } });

    const form = screen.getByRole("button", { name: "Start run" }).closest("form")!;
    fireEvent.submit(form);

    await waitFor(() => {
      expect(mockPush).toHaveBeenCalledWith("/agent-runs/test-run-id-123");
    });
  });
});
