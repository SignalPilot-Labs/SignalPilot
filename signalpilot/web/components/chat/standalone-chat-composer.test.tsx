import { act, useState } from "react";
import { createRoot, type Root } from "react-dom/client";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { StandaloneChatComposer } from "~/components/chat/standalone-chat-composer";

(
  globalThis as typeof globalThis & { IS_REACT_ACT_ENVIRONMENT: boolean }
).IS_REACT_ACT_ENVIRONMENT = true;

const MENTION_OPTIONS = ["revenue_by_region", "revenue_monthly", "orders"];

/** Stateful wrapper mirroring real usage: the page owns the draft state. */
function ComposerHarness({ onValue }: { onValue: (value: string) => void }) {
  const [value, setValue] = useState("");
  return (
    <StandaloneChatComposer
      value={value}
      onValueChange={(next) => {
        setValue(next);
        onValue(next);
      }}
      onSubmit={vi.fn()}
      submitDisabled={false}
      placeholder="Ask"
      mentionOptions={MENTION_OPTIONS}
    />
  );
}

/** Types into the textarea the way a user would: native value setter +
 * input event, so React's onChange (and the mention scanner) run. */
function typeIntoComposer(container: HTMLElement, text: string) {
  const textarea = container.querySelector("textarea");
  if (!textarea) throw new Error("composer textarea not found");
  const setter = Object.getOwnPropertyDescriptor(
    HTMLTextAreaElement.prototype,
    "value",
  )?.set;
  setter?.call(textarea, text);
  textarea.setSelectionRange(text.length, text.length);
  textarea.dispatchEvent(new Event("input", { bubbles: true }));
}

describe("Standalone Data Chat composer mentions", () => {
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
    vi.clearAllMocks();
  });

  it("suggests matching models while typing an @-mention and inserts the pick", async () => {
    const onValue = vi.fn();
    await act(async () => {
      root.render(<ComposerHarness onValue={onValue} />);
    });
    await act(async () => typeIntoComposer(container, "Compare @rev"));

    const options = [...container.querySelectorAll("button")].filter((button) =>
      button.textContent?.startsWith("revenue"),
    );
    expect(options.map((button) => button.textContent)).toEqual([
      "revenue_by_region",
      "revenue_monthly",
    ]);

    await act(async () =>
      options[0].dispatchEvent(
        new MouseEvent("mousedown", { bubbles: true, cancelable: true }),
      ),
    );
    expect(onValue).toHaveBeenLastCalledWith("Compare @revenue_by_region ");
  });

  it("does not open the mention popover for plain text", async () => {
    await act(async () => {
      root.render(<ComposerHarness onValue={vi.fn()} />);
    });
    await act(async () =>
      typeIntoComposer(
        container,
        "Compare this with the quarterly revenue numbers",
      ),
    );

    expect(
      [...container.querySelectorAll("button")].some((button) =>
        button.textContent?.includes("revenue_by_region"),
      ),
    ).toBe(false);
  });
});
