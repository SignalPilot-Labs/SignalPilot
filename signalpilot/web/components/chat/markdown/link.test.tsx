import { act } from "react";
import { createRoot, type Root } from "react-dom/client";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import {
  isPlainLeftClick,
  parseLineageHref,
} from "~/components/chat/lineage-modal/lineage-href";
import { MarkdownLink } from "./link";

(
  globalThis as typeof globalThis & { IS_REACT_ACT_ENVIRONMENT: boolean }
).IS_REACT_ACT_ENVIRONMENT = true;

// The real modal pulls in reactflow + dagre; a stub keeps this suite about
// the link's click routing.
vi.mock("~/components/chat/lineage-modal/lineage-modal", () => ({
  LineageModal: ({
    link,
    onClose,
  }: {
    link: { modelName: string; projectId: string; raw: boolean };
    onClose: () => void;
  }) => (
    <div data-testid="lineage-modal" data-project={link.projectId} data-raw={String(link.raw)}>
      {link.modelName}
      <button type="button" onClick={onClose}>
        close
      </button>
    </div>
  ),
}));

const flush = () => act(async () => {});

describe("parseLineageHref", () => {
  it("accepts /lineage/<model>?project=<id> with an optional /raw", () => {
    expect(parseLineageHref("/lineage/fct_orders?project=p1")).toEqual({
      modelName: "fct_orders",
      projectId: "p1",
      raw: false,
      href: "/lineage/fct_orders?project=p1",
    });
    expect(parseLineageHref("/lineage/model.jaffle.fct_orders/raw?project=p1")).toMatchObject({
      modelName: "model.jaffle.fct_orders",
      raw: true,
    });
    expect(parseLineageHref("/lineage/fct%20orders?project=p1&x=1")?.modelName).toBe(
      "fct orders",
    );
  });

  it("rejects links without a project, nested paths and other routes", () => {
    expect(parseLineageHref("/lineage/fct_orders")).toBeNull();
    expect(parseLineageHref("/lineage/fct_orders?branch=main")).toBeNull();
    expect(parseLineageHref("/lineage?project=p1")).toBeNull();
    expect(parseLineageHref("/lineage/a/b?project=p1")).toBeNull();
    expect(parseLineageHref("/knowledge/fct_orders?project=p1")).toBeNull();
    expect(parseLineageHref("https://x.test/lineage/fct_orders?project=p1")).toBeNull();
    expect(parseLineageHref(undefined)).toBeNull();
  });
});

describe("isPlainLeftClick", () => {
  const base = {
    button: 0,
    metaKey: false,
    ctrlKey: false,
    shiftKey: false,
    altKey: false,
    defaultPrevented: false,
  };
  it("is true only for an unmodified primary click", () => {
    expect(isPlainLeftClick(base)).toBe(true);
    expect(isPlainLeftClick({ ...base, button: 1 })).toBe(false);
    expect(isPlainLeftClick({ ...base, ctrlKey: true })).toBe(false);
    expect(isPlainLeftClick({ ...base, metaKey: true })).toBe(false);
    expect(isPlainLeftClick({ ...base, shiftKey: true })).toBe(false);
    expect(isPlainLeftClick({ ...base, altKey: true })).toBe(false);
    expect(isPlainLeftClick({ ...base, defaultPrevented: true })).toBe(false);
  });
});

describe("MarkdownLink lineage routing", () => {
  let container: HTMLDivElement;
  let root: Root;

  beforeEach(() => {
    container = document.createElement("div");
    document.body.appendChild(container);
    root = createRoot(container);
  });

  afterEach(async () => {
    await act(async () => root.unmount());
    container.remove();
  });

  async function render(href: string, label = "fct_orders") {
    await act(async () => {
      root.render(<MarkdownLink href={href}>{label}</MarkdownLink>);
    });
    const anchor = container.querySelector("a");
    if (!anchor) throw new Error("no anchor rendered");
    return anchor;
  }

  /**
   * Dispatch a click and report whether the link handler prevented it.
   * The document listener runs after React's and cancels the click itself,
   * so jsdom never attempts a real navigation.
   */
  function click(anchor: HTMLAnchorElement, init: MouseEventInit = {}) {
    const event = new MouseEvent("click", {
      bubbles: true,
      cancelable: true,
      button: 0,
      ...init,
    });
    let prevented = false;
    const observe = (e: Event) => {
      prevented = e.defaultPrevented;
      e.preventDefault();
    };
    document.addEventListener("click", observe);
    act(() => {
      anchor.dispatchEvent(event);
    });
    document.removeEventListener("click", observe);
    return { prevented };
  }

  const modal = () => document.querySelector('[data-testid="lineage-modal"]');

  it("keeps the real href and opens the modal on a plain click", async () => {
    const anchor = await render("/lineage/fct_orders?project=p1");
    expect(anchor.getAttribute("href")).toBe("/lineage/fct_orders?project=p1");
    expect(modal()).toBeNull();

    expect(click(anchor).prevented).toBe(true);
    await flush();
    expect(modal()?.textContent).toContain("fct_orders");
    expect(modal()?.getAttribute("data-project")).toBe("p1");

    act(() => {
      (modal()?.querySelector("button") as HTMLButtonElement).click();
    });
    expect(modal()).toBeNull();
  });

  it("passes the raw flag through", async () => {
    const anchor = await render("/lineage/fct_orders/raw?project=p1");
    click(anchor);
    await flush();
    expect(modal()?.getAttribute("data-raw")).toBe("true");
  });

  it("leaves modifier and middle clicks to the browser", async () => {
    const anchor = await render("/lineage/fct_orders?project=p1");
    for (const init of [
      { ctrlKey: true },
      { metaKey: true },
      { shiftKey: true },
      { button: 1 },
    ] satisfies MouseEventInit[]) {
      expect(click(anchor, init).prevented).toBe(false);
      await flush();
      expect(modal()).toBeNull();
    }
  });

  it("falls back to navigation when the href has no project", async () => {
    const anchor = await render("/lineage/fct_orders");
    expect(anchor.getAttribute("href")).toBe("/lineage/fct_orders");
    expect(anchor.hasAttribute("data-lineage-model")).toBe(false);
    click(anchor);
    await flush();
    expect(modal()).toBeNull();
  });

  it("renders other hrefs as before", async () => {
    const route = await render("/knowledge/fct_orders?project=p1");
    expect(route.getAttribute("target")).toBeNull();
    click(route);
    await flush();
    expect(modal()).toBeNull();

    const external = await render("https://docs.getdbt.com/", "dbt docs");
    expect(external.getAttribute("target")).toBe("_blank");
    expect(external.getAttribute("rel")).toBe("noopener noreferrer");
  });
});
