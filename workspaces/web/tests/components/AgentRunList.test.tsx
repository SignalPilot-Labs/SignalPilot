import React from "react";
import { describe, it, expect, afterEach, vi } from "vitest";
import { render, screen, cleanup } from "@testing-library/react";
import { AgentRunList } from "@/components/agent-runs/AgentRunList";
import type { AgentRunV1 } from "@/lib/agent-runs/types";

// Mock next/link so it renders as a plain <a> in jsdom
vi.mock("next/link", () => ({
  default: ({
    href,
    children,
    className,
  }: {
    href: string;
    children: React.ReactNode;
    className?: string;
  }) => (
    <a href={href} className={className}>
      {children}
    </a>
  ),
}));

afterEach(() => {
  cleanup();
});

function makeRun(overrides: Partial<AgentRunV1> = {}): AgentRunV1 {
  return {
    schemaVersion: 1,
    id: "aabbccdd-1234-4abc-8def-aabbccddeeff",
    prompt: "Test agent prompt",
    status: "pending",
    createdAt: "2024-06-01T00:00:00.000Z",
    ...overrides,
  };
}

describe("AgentRunList", () => {
  it("renders prompt text, status label, and Link href for each item", () => {
    const item = makeRun({
      id: "11111111-1111-4111-8111-111111111111",
      prompt: "Analyze sales pipeline",
      status: "pending",
    });

    render(<AgentRunList items={[item]} />);

    expect(screen.getByText("Analyze sales pipeline")).toBeDefined();
    expect(screen.getByText(/Pending/)).toBeDefined();

    const link = screen.getByRole("link", { name: /Analyze sales pipeline/ });
    expect(link.getAttribute("href")).toBe(`/agent-runs/${item.id}`);
  });

  it("renders empty <ul> with no children for empty array", () => {
    const { container } = render(<AgentRunList items={[]} />);
    const ul = container.querySelector("ul");
    expect(ul).toBeDefined();
    expect(ul?.children.length).toBe(0);
  });
});
