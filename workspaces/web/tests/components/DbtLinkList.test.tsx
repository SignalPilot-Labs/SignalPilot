import React from "react";
import { describe, it, expect, afterEach, vi } from "vitest";
import { render, screen, cleanup } from "@testing-library/react";
import { DbtLinkList } from "@/components/dbt-links/DbtLinkList";
import type { DbtLinkV1 } from "@/lib/dbt-links/types";

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

function makeLink(overrides: Partial<DbtLinkV1> = {}): DbtLinkV1 {
  return {
    schemaVersion: 1,
    id: "aabbccdd-1234-4abc-8def-aabbccddeeff",
    name: "Test Link",
    kind: "native_upload",
    createdAt: "2024-06-01T00:00:00.000Z",
    relativePath: "projects/test-project",
    ...overrides,
  };
}

describe("DbtLinkList", () => {
  it("renders all item names", () => {
    const items = [
      makeLink({ id: "11111111-1111-4111-8111-111111111111", name: "Alpha Project" }),
      makeLink({ id: "22222222-2222-4222-8222-222222222222", name: "Beta Project" }),
      makeLink({ id: "33333333-3333-4333-8333-333333333333", name: "Gamma Project" }),
    ];

    render(<DbtLinkList items={items} />);

    expect(screen.getByText("Alpha Project")).toBeDefined();
    expect(screen.getByText("Beta Project")).toBeDefined();
    expect(screen.getByText("Gamma Project")).toBeDefined();
  });

  it("renders humanized kind labels for each kind", () => {
    const uploadItem = makeLink({
      id: "11111111-1111-4111-8111-111111111111",
      name: "Upload Project",
      kind: "native_upload",
    });
    render(<DbtLinkList items={[uploadItem]} />);
    expect(screen.getAllByText(/Native upload/)).toHaveLength(1);

    cleanup();

    const githubItem = makeLink({
      id: "22222222-2222-4222-8222-222222222222",
      name: "Some Other Project",
      kind: "github",
    });
    render(<DbtLinkList items={[githubItem]} />);
    expect(screen.getAllByText(/GitHub/)).toHaveLength(1);

    cleanup();

    const cloudItem = makeLink({
      id: "33333333-3333-4333-8333-333333333333",
      name: "Cloud Project",
      kind: "dbt_cloud",
    });
    render(<DbtLinkList items={[cloudItem]} />);
    expect(screen.getAllByText(/dbt Cloud/)).toHaveLength(1);
  });

  it("each card is wrapped in an <a> link pointing to /dbt-links/<id>", () => {
    const item = makeLink({
      id: "44444444-4444-4444-8444-444444444444",
      name: "Linked Project",
    });
    render(<DbtLinkList items={[item]} />);

    const link = screen.getByRole("link", { name: /Linked Project/ });
    expect(link).toBeDefined();
    expect(link.getAttribute("href")).toBe(`/dbt-links/${item.id}`);
  });
});
