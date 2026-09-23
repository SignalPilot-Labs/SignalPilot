/**
 * `parseHtmlContent` turns kernel HTML output into plain text. It must parse
 * into an inert document: a detached `innerHTML` assignment still fires
 * `<img onerror>` handlers, an inert DOMParser document never does.
 */
import { describe, expect, it, vi } from "vitest";
import { ansiToPlainText, parseHtmlContent } from "./dom";

describe("parseHtmlContent", () => {
  it("strips tags and trims trailing whitespace per line", () => {
    expect(parseHtmlContent("<b>hello</b> <i>world</i>  \nline2   ")).toBe(
      "hello world\nline2",
    );
  });

  it("returns plain text unchanged", () => {
    expect(parseHtmlContent("plain text")).toBe("plain text");
    expect(parseHtmlContent("")).toBe("");
  });

  it("does not execute inline handlers or scripts while extracting text", () => {
    const spy = vi.fn();
    (window as unknown as { xssProbe?: () => void }).xssProbe = spy;
    const createElement = vi.spyOn(document, "createElement");
    const out = parseHtmlContent(
      `<img src=x onerror="window.xssProbe()"><script>window.xssProbe()</script>text`,
    );
    expect(out).toBe("window.xssProbe()text");
    expect(spy).not.toHaveBeenCalled();
    // The live document is never used as a parsing scratchpad.
    expect(createElement).not.toHaveBeenCalled();
    createElement.mockRestore();
    delete (window as unknown as { xssProbe?: () => void }).xssProbe;
  });

  it("converts ANSI sequences to plain text", () => {
    expect(ansiToPlainText("[31mred[0m and plain")).toBe("red and plain");
    expect(ansiToPlainText("")).toBe("");
  });
});
