/**
 * The chat live-notebook viewer (`viewerOnlyAtom`) shows agent-authored
 * output. Read/app mode normally switches sanitization OFF ("an app the
 * author trusts"); the viewer must force it ON and must never count as a
 * trusted notebook context (which would let `<script src>` through).
 */
import { createStore, Provider } from "jotai";
import { act } from "react";
import { createRoot, type Root } from "react-dom/client";
import { afterEach, describe, expect, it } from "vitest";
import { configOverridesAtom } from "@/core/config/config";
import { forcedModeAtom, viewerOnlyAtom } from "@/core/mode";
import { bindStore, unbindStore } from "@/core/state/store-binding";
import { hasTrustedNotebookContext } from "@/core/static/export-context";
import { useSanitizeHtml } from "./sanitize";

(
  globalThis as typeof globalThis & { IS_REACT_ACT_ENVIRONMENT: boolean }
).IS_REACT_ACT_ENVIRONMENT = true;

function Probe() {
  const sanitize = useSanitizeHtml();
  return <span data-testid="probe">{sanitize ? "sanitize" : "raw"}</span>;
}

describe("useSanitizeHtml", () => {
  let root: Root | undefined;
  let container: HTMLDivElement | undefined;
  let bound: ReturnType<typeof createStore> | undefined;

  afterEach(async () => {
    if (root) {
      await act(async () => root?.unmount());
    }
    container?.remove();
    if (bound) {
      unbindStore(bound);
    }
    root = undefined;
    container = undefined;
    bound = undefined;
  });

  async function renderWith(store: ReturnType<typeof createStore>) {
    // auto_instantiate defaults to true and is a trust signal of its own;
    // pin it off so the mode / viewer flags are what is under test.
    store.set(configOverridesAtom, { runtime: { auto_instantiate: false } });
    bindStore(store);
    bound = store;
    container = document.createElement("div");
    document.body.appendChild(container);
    root = createRoot(container);
    await act(async () => {
      root?.render(
        <Provider store={store}>
          <Probe />
        </Provider>,
      );
    });
    return container.querySelector('[data-testid="probe"]')?.textContent;
  }

  it("is off in read/app mode for a normal notebook", async () => {
    const store = createStore();
    store.set(forcedModeAtom, "read");
    expect(await renderWith(store)).toBe("raw");
  });

  it("is forced on for the viewer-only (chat) surface even in read mode", async () => {
    const store = createStore();
    store.set(forcedModeAtom, "read");
    store.set(viewerOnlyAtom, true);
    expect(await renderWith(store)).toBe("sanitize");
  });

  it("is on in edit mode before any cell has run", async () => {
    const store = createStore();
    store.set(forcedModeAtom, "edit");
    expect(await renderWith(store)).toBe("sanitize");
  });
});

describe("hasTrustedNotebookContext", () => {
  let bound: ReturnType<typeof createStore> | undefined;

  afterEach(() => {
    if (bound) {
      unbindStore(bound);
    }
    bound = undefined;
  });

  it("trusts read/app mode for a normal notebook", () => {
    const store = createStore();
    store.set(configOverridesAtom, { runtime: { auto_instantiate: false } });
    store.set(forcedModeAtom, "read");
    bindStore(store);
    bound = store;
    expect(hasTrustedNotebookContext()).toBe(true);
  });

  it("never trusts the viewer-only (chat) surface", () => {
    const store = createStore();
    store.set(forcedModeAtom, "read");
    store.set(viewerOnlyAtom, true);
    bindStore(store);
    bound = store;
    expect(hasTrustedNotebookContext()).toBe(false);
  });
});
