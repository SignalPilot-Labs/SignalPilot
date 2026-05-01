import { describe, it, expect, afterEach } from "vitest";
import { render, screen, cleanup } from "@testing-library/react";
import { DbtLinkDetail } from "@/components/dbt-links/DbtLinkDetail";
import type { DbtLinkV1 } from "@/lib/dbt-links/types";

afterEach(() => {
  cleanup();
});

function makeLink(overrides: Partial<DbtLinkV1> = {}): DbtLinkV1 {
  return {
    schemaVersion: 1,
    id: "aabbccdd-1234-4abc-8def-aabbccddeeff",
    name: "Test Link",
    kind: "native_upload",
    createdAt: "2024-06-15T12:00:00.000Z",
    relativePath: "aabbccdd-1234-4abc-8def-aabbccddeeff",
    ...overrides,
  };
}

describe("DbtLinkDetail", () => {
  it("renders the link name, kind label, and relativePath", () => {
    const link = makeLink({ name: "My dbt Project" });
    render(<DbtLinkDetail link={link} />);

    expect(screen.getByRole("heading", { level: 1, name: "My dbt Project" })).toBeDefined();
    expect(screen.getByText("Native upload")).toBeDefined();
    expect(screen.getByText(link.relativePath)).toBeDefined();
  });

  it("renders relativePath inside a <code> element", () => {
    const link = makeLink();
    render(<DbtLinkDetail link={link} />);

    const pathEl = screen.getByText(link.relativePath);
    expect(pathEl.tagName.toLowerCase()).toBe("code");
  });

  it("renders the correct kind label for github kind", () => {
    const link = makeLink({ kind: "github" });
    render(<DbtLinkDetail link={link} />);
    expect(screen.getByText("GitHub")).toBeDefined();
  });
});
