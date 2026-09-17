/**
 * `replaceValidIframes` re-creates iframes through `dangerouslySetInnerHTML`
 * so authors' event attributes survive in a TRUSTED notebook (folium and
 * friends rely on `onload` + same-origin `contentDocument`). Outside a
 * trusted context (the chat viewer, edit mode before any run) the iframe
 * must lose its inline handlers and gain an opaque-origin sandbox.
 */
import { createStore, Provider } from "jotai";
import { act } from "react";
import { createRoot, type Root } from "react-dom/client";
import { afterEach, describe, expect, it } from "vitest";
import { forcedModeAtom, viewerOnlyAtom } from "@/core/mode";
import { bindStore, unbindStore } from "@/core/state/store-binding";
import { renderHTML, visibleForTesting } from "./RenderHTML";

(
  globalThis as typeof globalThis & { IS_REACT_ACT_ENVIRONMENT: boolean }
).IS_REACT_ACT_ENVIRONMENT = true;

const IFRAME_ONLOAD = `<iframe onload="alert(1)" src="about:blank" allowfullscreen></iframe>`;
const IFRAME_SRCDOC = `<iframe srcdoc="&lt;script&gt;parent.document.title='pwned'&lt;/script&gt;" sandbox="allow-same-origin allow-scripts"></iframe>`;

async function mount(node: React.ReactNode, store: ReturnType<typeof createStore>) {
  const host = document.createElement("div");
  document.body.appendChild(host);
  const root: Root = createRoot(host);
  await act(async () => {
    root.render(<Provider store={store}>{node}</Provider>);
  });
  const iframe = host.querySelector("iframe");
  await act(async () => root.unmount());
  host.remove();
  return iframe;
}

describe("replaceValidIframes", () => {
  let bound: ReturnType<typeof createStore> | undefined;

  afterEach(() => {
    if (bound) unbindStore(bound);
    bound = undefined;
    delete window.__SP_EXPORT_CONTEXT__;
  });

  function bindViewer(viewerOnly: boolean) {
    const store = createStore();
    store.set(forcedModeAtom, "read");
    store.set(viewerOnlyAtom, viewerOnly);
    bindStore(store);
    bound = store;
    return store;
  }

  it("keeps author attributes in a trusted notebook (read mode)", async () => {
    const store = bindViewer(false);
    const iframe = await mount(visibleForTesting.parseHtml({ html: IFRAME_ONLOAD }), store);
    expect(iframe?.getAttribute("onload")).toBe("alert(1)");
    expect(iframe?.hasAttribute("sandbox")).toBe(false);
    expect(iframe?.hasAttribute("allowfullscreen")).toBe(true);
  });

  it("strips on* handlers and sandboxes the frame in the chat viewer", async () => {
    const store = bindViewer(true);
    const iframe = await mount(visibleForTesting.parseHtml({ html: IFRAME_ONLOAD }), store);
    expect(iframe).not.toBeNull();
    expect(iframe?.hasAttribute("onload")).toBe(false);
    expect(iframe?.getAttribute("sandbox")).toBe("allow-scripts allow-forms allow-popups");
    expect(iframe?.getAttribute("src")).toBe("about:blank");
    expect(iframe?.hasAttribute("allowfullscreen")).toBe(true);
  });

  it("replaces an author-supplied sandbox so srcdoc never gets same-origin", async () => {
    const store = bindViewer(true);
    const iframe = await mount(visibleForTesting.parseHtml({ html: IFRAME_SRCDOC }), store);
    const sandbox = iframe?.getAttribute("sandbox") ?? "";
    expect(sandbox).not.toContain("allow-same-origin");
    expect(sandbox).not.toContain("allow-top-navigation");
    expect(sandbox).toContain("allow-scripts");
  });

  it("in the chat viewer the full render path sanitizes: iframes are removed", async () => {
    const store = bindViewer(true);
    const iframe = await mount(
      renderHTML({ html: IFRAME_SRCDOC + IFRAME_ONLOAD, alwaysSanitizeHtml: false }),
      store,
    );
    expect(iframe).toBeNull();
  });

  it("in a trusted read-mode notebook the full render path still keeps iframes", async () => {
    const store = bindViewer(false);
    const iframe = await mount(
      renderHTML({ html: IFRAME_ONLOAD, alwaysSanitizeHtml: false }),
      store,
    );
    expect(iframe?.getAttribute("onload")).toBe("alert(1)");
    expect(iframe?.hasAttribute("sandbox")).toBe(false);
  });
});
