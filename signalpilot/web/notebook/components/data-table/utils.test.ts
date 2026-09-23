/**
 * Clipboard text for text/html cells is derived by stripping tags. The strip
 * must happen in an inert DOMParser document so that `<img onerror>` in a
 * warehouse cell never runs while the user copies it.
 */
import { describe, expect, it, vi } from "vitest";
import { getClipboardContent } from "./utils";

const htmlCell = (data: string) => [{ mimetype: "text/html", data }];

describe("getClipboardContent for text/html cells", () => {
  it("copies the visible text and keeps the html part", () => {
    const out = getClipboardContent(undefined, htmlCell("<b>bold</b> text"));
    expect(out.text).toBe("bold text");
    expect(out.html).toBe("<b>bold</b> text");
  });

  it("falls back to the raw html when it has no text", () => {
    expect(getClipboardContent(undefined, htmlCell("<img src=x>")).text).toBe("<img src=x>");
  });

  it("does not execute handlers while stripping", () => {
    const spy = vi.fn();
    (window as unknown as { xssProbe?: () => void }).xssProbe = spy;
    const createElement = vi.spyOn(document, "createElement");
    const out = getClipboardContent(
      undefined,
      htmlCell(`<img src=x onerror="window.xssProbe()">cell`),
    );
    expect(out.text).toBe("cell");
    expect(spy).not.toHaveBeenCalled();
    expect(createElement).not.toHaveBeenCalled();
    createElement.mockRestore();
    delete (window as unknown as { xssProbe?: () => void }).xssProbe;
  });
});
