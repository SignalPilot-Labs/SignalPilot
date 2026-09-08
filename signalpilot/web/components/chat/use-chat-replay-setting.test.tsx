import { act } from "react";
import { createRoot, type Root } from "react-dom/client";
import { afterEach, beforeEach, describe, expect, it } from "vitest";

import {
  CHAT_REPLAY_STORAGE_KEY,
  setChatReplayEnabled,
  useChatReplaySetting,
} from "~/components/chat/use-chat-replay-setting";

(
  globalThis as typeof globalThis & { IS_REACT_ACT_ENVIRONMENT: boolean }
).IS_REACT_ACT_ENVIRONMENT = true;

function Probe() {
  const enabled = useChatReplaySetting();
  return (
    <button type="button" aria-pressed={enabled} onClick={() => setChatReplayEnabled(!enabled)}>
      Toggle
    </button>
  );
}

describe("chat replay local setting", () => {
  let container: HTMLDivElement;
  let root: Root;

  beforeEach(() => {
    window.localStorage.removeItem(CHAT_REPLAY_STORAGE_KEY);
    container = document.createElement("div");
    document.body.appendChild(container);
    root = createRoot(container);
  });

  afterEach(async () => {
    await act(async () => root.unmount());
    window.localStorage.removeItem(CHAT_REPLAY_STORAGE_KEY);
    container.remove();
  });

  it("defaults off and persists an opt-in only in local storage", async () => {
    await act(async () => root.render(<Probe />));
    const toggle = container.querySelector("button")!;
    expect(toggle.getAttribute("aria-pressed")).toBe("false");
    expect(window.localStorage.getItem(CHAT_REPLAY_STORAGE_KEY)).toBeNull();

    await act(async () => toggle.click());
    expect(toggle.getAttribute("aria-pressed")).toBe("true");
    expect(window.localStorage.getItem(CHAT_REPLAY_STORAGE_KEY)).toBe("true");

    await act(async () => toggle.click());
    expect(toggle.getAttribute("aria-pressed")).toBe("false");
    expect(window.localStorage.getItem(CHAT_REPLAY_STORAGE_KEY)).toBeNull();
  });
});
