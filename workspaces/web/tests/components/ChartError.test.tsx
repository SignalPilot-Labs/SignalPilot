import { describe, it, expect, afterEach } from "vitest";
import { render, screen, cleanup } from "@testing-library/react";
import { ChartError } from "@/components/charts/ChartError";

afterEach(() => {
  cleanup();
});

describe("ChartError", () => {
  it("renders alert div with badge-error class and role=alert", () => {
    render(<ChartError message="Something went wrong" />);
    const alert = screen.getByRole("alert");
    expect(alert).toBeDefined();
    expect(alert.className).toContain("badge-error");
    expect(alert.className).toContain("border");
  });

  it("renders default message when message prop is omitted", () => {
    render(<ChartError />);
    const alert = screen.getByRole("alert");
    expect(alert.textContent).toContain("An error occurred while loading this chart.");
  });

  it("renders supplied message", () => {
    render(<ChartError message="Custom error message" />);
    const alert = screen.getByRole("alert");
    expect(alert.textContent).toContain("Custom error message");
  });
});
