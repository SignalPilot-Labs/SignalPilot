import { describe, it, expect, afterEach } from "vitest";
import { render, screen, cleanup } from "@testing-library/react";
import { EmptyState } from "@/components/ui/EmptyState";

afterEach(() => {
  cleanup();
});

describe("EmptyState", () => {
  it("renders required title and body", () => {
    render(<EmptyState title="Workspaces" body="Nothing here yet." />);
    expect(screen.getByRole("heading", { level: 2 }).textContent).toBe("Workspaces");
    expect(screen.getByText("Nothing here yet.")).toBeDefined();
  });
});
