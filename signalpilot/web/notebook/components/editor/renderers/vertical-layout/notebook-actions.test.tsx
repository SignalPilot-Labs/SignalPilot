import { createStore, Provider } from "jotai";
import { act } from "react";
import { createRoot, type Root } from "react-dom/client";
import { afterEach, beforeEach, describe, expect, it } from "vitest";
import { viewerOnlyAtom } from "@/core/mode";
import { requestClientAtom } from "@/core/network/requests";
import { NotebookActionButtons } from "./notebook-actions";

(
  globalThis as typeof globalThis & { IS_REACT_ACT_ENVIRONMENT: boolean }
).IS_REACT_ACT_ENVIRONMENT = true;

const DROPDOWN = '[data-testid="notebook-actions-dropdown"]';

describe("NotebookActionButtons", () => {
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

  async function render(viewerOnly: boolean) {
    const store = createStore();
    store.set(viewerOnlyAtom, viewerOnly);
    // The menu only needs readCode, and only when an item is selected.
    store.set(requestClientAtom, {
      readCode: async () => ({ contents: "" }),
    } as never);
    await act(async () => {
      root.render(
        <Provider store={store}>
          <NotebookActionButtons
            canShowCode={true}
            showCode={false}
            onToggleShowCode={() => {}}
          />
        </Provider>,
      );
    });
  }

  it("renders the three-dots trigger in the full notebook app", async () => {
    await render(false);
    const dropdown = container.querySelector(DROPDOWN);
    expect(dropdown).not.toBeNull();
    const trigger = dropdown?.querySelector('button[aria-haspopup="menu"]');
    expect(trigger).not.toBeNull();
    expect(trigger?.querySelector("svg.lucide-ellipsis")).not.toBeNull();
  });

  it("renders nothing on viewer-only surfaces (chat notebook panel)", async () => {
    await render(true);
    expect(container.querySelector(DROPDOWN)).toBeNull();
    expect(container.querySelector('button[aria-haspopup="menu"]')).toBeNull();
  });
});
