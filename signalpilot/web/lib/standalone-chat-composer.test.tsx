import { StrictMode, act, useState } from "react";
import { createRoot, type Root } from "react-dom/client";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { StandaloneChatComposer } from "~/components/chat/standalone-chat-composer";

(
  globalThis as typeof globalThis & { IS_REACT_ACT_ENVIRONMENT: boolean }
).IS_REACT_ACT_ENVIRONMENT = true;

function setTextareaValue(textarea: HTMLTextAreaElement, value: string) {
  const setter = Object.getOwnPropertyDescriptor(
    HTMLTextAreaElement.prototype,
    "value",
  )?.set;
  setter?.call(textarea, value);
  textarea.dispatchEvent(new Event("input", { bubbles: true }));
}

describe("StandaloneChatComposer", () => {
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

  it("keeps typed text under StrictMode even while submission is disabled", async () => {
    const onSubmit = vi.fn(async () => true);

    function Harness() {
      const [value, setValue] = useState("");
      return (
        <StandaloneChatComposer
          value={value}
          onValueChange={setValue}
          onSubmit={onSubmit}
          submitDisabled
          placeholder="Ask a question"
        />
      );
    }

    await act(async () => {
      root.render(
        <StrictMode>
          <Harness />
        </StrictMode>,
      );
    });

    const textarea = container.querySelector("textarea");
    const sendButton = container.querySelector<HTMLButtonElement>(
      'button[aria-label="Send message"]',
    );

    expect(textarea?.disabled).toBe(false);
    expect(sendButton?.disabled).toBe(true);

    await act(async () => {
      setTextareaValue(textarea!, "show me daily revenue");
    });

    expect(textarea?.value).toBe("show me daily revenue");

    await act(async () => {
      textarea?.dispatchEvent(
        new KeyboardEvent("keydown", { key: "Enter", bubbles: true }),
      );
    });

    expect(onSubmit).not.toHaveBeenCalled();
    expect(textarea?.value).toBe("show me daily revenue");
  });

  it("submits and clears the controlled draft when enabled", async () => {
    const onSubmit = vi.fn(async () => true);

    function Harness() {
      const [value, setValue] = useState("");
      return (
        <StandaloneChatComposer
          value={value}
          onValueChange={setValue}
          onSubmit={onSubmit}
          submitDisabled={false}
          placeholder="Ask a question"
        />
      );
    }

    await act(async () => {
      root.render(
        <StrictMode>
          <Harness />
        </StrictMode>,
      );
    });

    const textarea = container.querySelector("textarea");
    await act(async () => {
      setTextareaValue(textarea!, "show me daily revenue");
    });
    await act(async () => {
      textarea?.dispatchEvent(
        new KeyboardEvent("keydown", { key: "Enter", bubbles: true }),
      );
    });

    expect(onSubmit).toHaveBeenCalledOnce();
    expect(onSubmit).toHaveBeenCalledWith("show me daily revenue");
    expect(textarea?.value).toBe("");
  });

  it("shows send and stop together while an agent is running", async () => {
    const onSubmit = vi.fn();
    const onStop = vi.fn();

    function Harness() {
      const [value, setValue] = useState("Use weekly data");
      return (
        <StandaloneChatComposer
          value={value}
          onValueChange={setValue}
          onSubmit={onSubmit}
          submitDisabled={false}
          running
          onStop={onStop}
          placeholder="Add an instruction"
        />
      );
    }

    await act(async () => root.render(<Harness />));
    const queueButton = container.querySelector<HTMLButtonElement>(
      'button[aria-label="Queue message for the running agent"]',
    );
    const stopButton = container.querySelector<HTMLButtonElement>(
      'button[aria-label="Stop the running analysis"]',
    );
    expect(queueButton).not.toBeNull();
    expect(stopButton).not.toBeNull();
    expect(container.textContent).toContain("Enter to queue for the next turn");

    await act(async () => queueButton?.click());
    expect(onSubmit).toHaveBeenCalledWith("Use weekly data");
    expect(onStop).not.toHaveBeenCalled();
  });
});
