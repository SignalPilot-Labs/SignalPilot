import { describe, it, expect, afterEach } from "vitest";
import { render, screen, cleanup } from "@testing-library/react";
import { EmptyState } from "@/components/dashboard/EmptyState";

afterEach(() => {
  cleanup();
});

describe("EmptyState", () => {
  it("renders required title and body", () => {
    render(<EmptyState title="Workspaces" body="Nothing here yet." />);
    const section = screen.getByRole("status");
    expect(section).toBeDefined();
    expect(screen.getByRole("heading", { level: 2 }).textContent).toBe("Workspaces");
    expect(screen.getByText("Nothing here yet.")).toBeDefined();
  });
});
