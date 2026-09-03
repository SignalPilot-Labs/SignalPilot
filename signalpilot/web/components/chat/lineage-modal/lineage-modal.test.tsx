import { act, useEffect } from "react";
import { createRoot, type Root } from "react-dom/client";
import { afterEach, beforeEach, describe, expect, it, vi, type Mock } from "vitest";
import type { LineageHref } from "./lineage-href";
import { LineageModal } from "./lineage-modal";

(
  globalThis as typeof globalThis & { IS_REACT_ACT_ENVIRONMENT: boolean }
).IS_REACT_ACT_ENVIRONMENT = true;

// Stand-in for the real map: reports a status keyed on the project id and
// crashes on demand, so the shell's states can be driven without a gateway.
vi.mock("~/components/lineage/lineage-embed", () => ({
  LineageEmbed: ({
    modelName,
    projectId,
    raw,
    onStatusChange,
  }: {
    modelName: string;
    projectId: string;
    raw?: boolean;
    onStatusChange?: (status: string) => void;
  }) => {
    if (projectId === "crash") throw new Error("boom");
    useEffect(() => {
      onStatusChange?.(projectId === "broken" ? "error" : "success");
    }, [projectId, onStatusChange]);
    return (
      <div data-testid="embed-stub" data-raw={String(Boolean(raw))}>
        map of {modelName}
      </div>
    );
  },
}));

const link = (overrides: Partial<LineageHref> = {}): LineageHref => ({
  modelName: "fct_orders",
  projectId: "p1",
  raw: false,
  href: "/lineage/fct_orders?project=p1",
  ...overrides,
});

const q = (testId: string) => document.querySelector(`[data-testid="${testId}"]`);

describe("LineageModal", () => {
  let container: HTMLDivElement;
  let root: Root;
  let onClose: Mock<() => void>;

  beforeEach(() => {
    container = document.createElement("div");
    document.body.appendChild(container);
    root = createRoot(container);
    onClose = vi.fn<() => void>();
    vi.spyOn(console, "error").mockImplementation(() => undefined);
  });

  afterEach(async () => {
    await act(async () => root.unmount());
    container.remove();
    vi.restoreAllMocks();
  });

  async function render(l: LineageHref) {
    await act(async () => {
      root.render(<LineageModal link={l} onClose={onClose} />);
    });
  }

  it("shows the model, the full-page link and the embedded map", async () => {
    await render(link());
    const dialog = q("lineage-modal");
    expect(dialog?.getAttribute("role")).toBe("dialog");
    expect(dialog?.getAttribute("aria-modal")).toBe("true");
    expect(q("lineage-modal-title")?.textContent).toBe("fct_orders");
    expect(q("lineage-modal-open-page")?.getAttribute("href")).toBe(
      "/lineage/fct_orders?project=p1",
    );
    expect(q("embed-stub")?.textContent).toContain("map of fct_orders");
    expect(q("lineage-modal-loading")).toBeNull();
    expect(q("lineage-modal-error")).toBeNull();
    expect(document.body.style.overflow).toBe("hidden");
  });

  it("labels the raw-tables view and passes the flag down", async () => {
    await render(link({ raw: true, href: "/lineage/fct_orders/raw?project=p1" }));
    expect(q("lineage-modal-title")?.textContent).toBe("fct_orders · raw tables");
    expect(q("embed-stub")?.getAttribute("data-raw")).toBe("true");
  });

  it("closes on Escape, backdrop click and the close button", async () => {
    await render(link());
    act(() => {
      window.dispatchEvent(new KeyboardEvent("keydown", { key: "Escape", bubbles: true }));
    });
    expect(onClose).toHaveBeenCalledTimes(1);

    act(() => {
      (q("lineage-modal-backdrop") as HTMLElement).click();
    });
    expect(onClose).toHaveBeenCalledTimes(2);

    // Clicks inside the panel do not close.
    act(() => {
      (q("lineage-modal-title") as HTMLElement).click();
    });
    expect(onClose).toHaveBeenCalledTimes(2);

    act(() => {
      (q("lineage-modal-close") as HTMLElement).click();
    });
    expect(onClose).toHaveBeenCalledTimes(3);
  });

  it("restores body scroll and the opener's focus on unmount", async () => {
    const opener = document.createElement("button");
    document.body.appendChild(opener);
    opener.focus();
    await render(link());
    expect(document.body.style.overflow).toBe("hidden");
    // jsdom has no layout, so the trap's offsetParent filter finds nothing to
    // focus here; the browser e2e covers focus entering the dialog.
    await act(async () => root.unmount());
    expect(document.body.style.overflow).toBe("");
    expect(document.activeElement).toBe(opener);
    opener.remove();
    root = createRoot(container);
  });

  it("shows the error state with the full-page link when the map fails to load", async () => {
    await render(link({ projectId: "broken", href: "/lineage/fct_orders?project=broken" }));
    const error = q("lineage-modal-error");
    expect(error?.textContent).toContain("could not be loaded");
    expect(error?.querySelector("a")?.getAttribute("href")).toBe(
      "/lineage/fct_orders?project=broken",
    );
    expect(q("embed-stub")).toBeNull();
    expect(q("lineage-modal-loading")).toBeNull();
    // Header actions survive the failure.
    expect(q("lineage-modal-open-page")).not.toBeNull();
    expect(q("lineage-modal-close")).not.toBeNull();
  });

  it("turns a render crash inside the map into the error state", async () => {
    await render(link({ projectId: "crash" }));
    expect(q("lineage-modal-error")).not.toBeNull();
    expect(q("embed-stub")).toBeNull();
  });
});
