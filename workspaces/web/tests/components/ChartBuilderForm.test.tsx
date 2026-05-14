import { describe, it, expect, vi, afterEach } from "vitest";
import { render, screen, cleanup, fireEvent, waitFor } from "@testing-library/react";

const pushMock = vi.fn();

// Mock next/navigation before importing the form
vi.mock("next/navigation", () => ({
  useRouter: () => ({ push: pushMock }),
}));

// Mock the server action module before importing the form
vi.mock("@/lib/charts/save-chart", () => ({
  saveChartDefinition: vi.fn(),
}));

import { ChartBuilderForm } from "@/components/charts/builder/ChartBuilderForm";
import { saveChartDefinition } from "@/lib/charts/save-chart";

afterEach(() => {
  cleanup();
  vi.clearAllMocks();
});

describe("ChartBuilderForm", () => {
  it("renders name input, type select, sql textarea, and submit button", () => {
    render(<ChartBuilderForm />);

    expect(screen.getByLabelText("Name")).toBeDefined();
    expect(screen.getByLabelText("Chart type")).toBeDefined();
    expect(screen.getByLabelText("SQL query")).toBeDefined();
    expect(screen.getByRole("button", { name: "Save" })).toBeDefined();
  });

  it("shows inline error and does NOT call the action or router.push when name is empty", async () => {
    render(<ChartBuilderForm />);

    // Leave name empty, submit
    fireEvent.submit(screen.getByRole("button", { name: "Save" }).closest("form")!);

    await waitFor(() => {
      expect(screen.getByRole("alert")).toBeDefined();
      expect(screen.getByText("Name is required.")).toBeDefined();
    });

    expect(saveChartDefinition).not.toHaveBeenCalled();
    expect(pushMock).not.toHaveBeenCalled();
  });

  it("calls the action with correct input and calls router.push with the new chart id on success", async () => {
    const mockId = "aabbccdd-1234-4abc-8def-aabbccddeeff";
    vi.mocked(saveChartDefinition).mockResolvedValueOnce({ ok: true, id: mockId });

    render(<ChartBuilderForm />);

    fireEvent.change(screen.getByLabelText("Name"), { target: { value: "Revenue Chart" } });
    fireEvent.change(screen.getByLabelText("SQL query"), { target: { value: "SELECT 1" } });
    fireEvent.submit(screen.getByRole("button", { name: "Save" }).closest("form")!);

    await waitFor(() => {
      expect(pushMock).toHaveBeenCalledOnce();
    });

    expect(pushMock).toHaveBeenCalledWith(`/charts/${mockId}`);
    expect(saveChartDefinition).toHaveBeenCalledOnce();
    expect(saveChartDefinition).toHaveBeenCalledWith({
      name: "Revenue Chart",
      type: "bar",
      sql: "SELECT 1",
    });
  });
});
