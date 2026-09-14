import React, { act } from "react";
import { createRoot, type Root } from "react-dom/client";
import { afterEach, beforeEach, expect, it } from "vitest";
import type { StandaloneChatEvent } from "~/lib/api";
import { ChatErrorDetails } from "./chat-error-details";

let container: HTMLDivElement;
let root: Root;
beforeEach(() => { container = document.createElement("div"); document.body.appendChild(container); root = createRoot(container); });
afterEach(() => { act(() => root.unmount()); container.remove(); });
function event(payload: Record<string, unknown>, runId = "run"): StandaloneChatEvent {
  return { run_id: runId, sequence: 1, type: "error", payload, created_at: "2026-09-09T00:00:00Z" };
}
it("shows expandable original error and stderr as plaintext with truncation notices", () => {
  act(() => root.render(<ChatErrorDetails runId="run" events={[event({ raw_error: "<script>error</script> [REDACTED]", stderr: '<img src=x onerror="alert(1)"> CLI failure', raw_error_truncated: true, stderr_truncated: true })]} />));
  const details = container.querySelector("details")!;
  expect(details.open).toBe(false);
  expect(details.textContent).toContain("<script>error</script> [REDACTED]");
  expect(details.textContent).toContain("CLI failure");
  expect(details.textContent).toContain("Original error was truncated");
  expect(details.textContent).toContain("Standard error was truncated");
  expect(details.querySelector("script, img")).toBeNull();
});
it("uses the current run diagnostics without exposing other runs or generic event fields", () => {
  act(() => root.render(<ChatErrorDetails runId="run" events={[event({ raw_error: "current", unrelated: "not shown" }), event({ raw_error: "another run" }, "other")]} />));
  expect(container.textContent).toContain("current");
  expect(container.textContent).not.toContain("another run");
  expect(container.textContent).not.toContain("not shown");
  expect(container.textContent).not.toContain("was truncated");
});
it("adds no diagnostics panel when the gateway supplied none", () => {
  act(() => root.render(<ChatErrorDetails runId="run" events={[event({ message: "Generic failure" })]} />));
  expect(container.querySelector("details")).toBeNull();
});
