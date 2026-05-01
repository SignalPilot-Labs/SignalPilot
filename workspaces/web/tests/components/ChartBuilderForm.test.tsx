import { describe, it, expect, vi, afterEach } from "vitest";
import { render, screen, cleanup, fireEvent, waitFor } from "@testing-library/react";

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

  it("shows inline error and does NOT call the action when name is empty", async () => {
    render(<ChartBuilderForm />);

    // Leave name empty, submit
    fireEvent.submit(screen.getByRole("button", { name: "Save" }).closest("form")!);

    await waitFor(() => {
      expect(screen.getByRole("alert")).toBeDefined();
      expect(screen.getByText("Name is required.")).toBeDefined();
    });

    expect(saveChartDefinition).not.toHaveBeenCalled();
  });

  it("calls the action once with correct input and renders success copy with id", async () => {
    const mockId = "aabbccdd-1234-4abc-8def-aabbccddeeff";
    vi.mocked(saveChartDefinition).mockResolvedValueOnce({ ok: true, id: mockId });

    render(<ChartBuilderForm />);

    fireEvent.change(screen.getByLabelText("Name"), { target: { value: "Revenue Chart" } });
    fireEvent.change(screen.getByLabelText("SQL query"), { target: { value: "SELECT 1" } });
    fireEvent.submit(screen.getByRole("button", { name: "Save" }).closest("form")!);

    await waitFor(() => {
      expect(screen.getByRole("status")).toBeDefined();
      expect(screen.getByText(`Saved as ${mockId}`)).toBeDefined();
    });

    expect(saveChartDefinition).toHaveBeenCalledOnce();
    expect(saveChartDefinition).toHaveBeenCalledWith({
      name: "Revenue Chart",
      type: "bar",
      sql: "SELECT 1",
    });
  });
});
