import { act } from "react";
import { createRoot, type Root } from "react-dom/client";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { StandaloneArtifactContext } from "~/components/chat/standalone-artifact-context";

(
  globalThis as typeof globalThis & { IS_REACT_ACT_ENVIRONMENT: boolean }
).IS_REACT_ACT_ENVIRONMENT = true;

describe("StandaloneArtifactContext", () => {
  let container: HTMLDivElement;
  let root: Root;
  let measuredScrollHeight: number;
  let originalScrollHeight: PropertyDescriptor | undefined;

  beforeEach(() => {
    measuredScrollHeight = 180;
    originalScrollHeight = Object.getOwnPropertyDescriptor(
      HTMLElement.prototype,
      "scrollHeight",
    );
    Object.defineProperty(HTMLElement.prototype, "scrollHeight", {
      configurable: true,
      get() {
        return this.hasAttribute("data-artifact-context-content")
          ? measuredScrollHeight
          : 0;
      },
    });
    vi.stubGlobal(
      "ResizeObserver",
      class {
        observe() {}
        disconnect() {}
      },
    );
    container = document.createElement("div");
    document.body.appendChild(container);
    root = createRoot(container);
  });

  afterEach(async () => {
    await act(async () => root.unmount());
    container.remove();
    vi.unstubAllGlobals();
    if (originalScrollHeight) {
      Object.defineProperty(
        HTMLElement.prototype,
        "scrollHeight",
        originalScrollHeight,
      );
    } else {
      delete (HTMLElement.prototype as Partial<HTMLElement>).scrollHeight;
    }
  });

  it("turns overflowing attachment context into a clickable collapsed box", async () => {
    await act(async () => {
      root.render(
        <StandaloneArtifactContext
          artifact={{
            freshness_at: "2026-08-03T00:00:00Z",
            assumptions: [
              "All monetary values converted to USD",
              "Latest ledger balance used",
            ],
            exclusions: ["Individual customer PII excluded"],
            caveats: ["Some queries used LIMIT clauses"],
          }}
        />,
      );
    });

    expect(container.querySelector("p")?.textContent).toContain(
      "Fresh through",
    );
    const box = container.querySelector<HTMLElement>('[role="button"]');
    const content = container.querySelector<HTMLElement>(
      "[data-artifact-context-content]",
    );
    expect(box?.getAttribute("aria-expanded")).toBe("false");
    expect(box?.className).toContain("shadow-");
    expect(content?.className).toContain("max-h-28");
    expect(container.textContent).not.toContain("Show more");
    expect(container.textContent).not.toContain("Show less");

    await act(async () => box?.click());

    expect(box?.getAttribute("aria-expanded")).toBe("true");
    expect(content?.className).not.toContain("max-h-28");
    expect(
      [...container.querySelectorAll("section")].map((section) => ({
        heading: section.querySelector("p")?.textContent,
        items: [...section.querySelectorAll("li")].map(
          (item) => item.textContent,
        ),
      })),
    ).toEqual([
      {
        heading: "Assumptions",
        items: [
          "All monetary values converted to USD",
          "Latest ledger balance used",
        ],
      },
      { heading: "Exclusions", items: ["Individual customer PII excluded"] },
      { heading: "Caveats", items: ["Some queries used LIMIT clauses"] },
    ]);
    expect(container.textContent).not.toContain("Assumption:");
    expect(container.textContent).not.toContain("Exclusion:");
    expect(container.textContent).not.toContain("Caveat:");
  });

  it("leaves short attachment context fully visible and non-clickable", async () => {
    measuredScrollHeight = 80;
    await act(async () => {
      root.render(
        <StandaloneArtifactContext
          artifact={{
            freshness_at: null,
            assumptions: ["Booked revenue only"],
            exclusions: [],
            caveats: [],
          }}
        />,
      );
    });

    expect(container.querySelector('[role="button"]')).toBeNull();
    expect(
      container.querySelector("[data-artifact-context-content]")?.className,
    ).not.toContain("max-h-28");
    expect(container.textContent).toContain("Booked revenue only");
  });
});
