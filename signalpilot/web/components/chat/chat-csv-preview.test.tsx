import { act } from "react";
import { createRoot, type Root } from "react-dom/client";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import {
  ChatCsvPreview,
  delimiterForFilename,
  isNumericColumn,
  parseDelimited,
} from "./chat-csv-preview";

(
  globalThis as typeof globalThis & { IS_REACT_ACT_ENVIRONMENT: boolean }
).IS_REACT_ACT_ENVIRONMENT = true;

describe("parseDelimited", () => {
  it("splits simple rows and drops blank lines", () => {
    const parsed = parseDelimited("a,b,c\n1,2,3\n\n4,5,6\n");
    expect(parsed.header).toEqual(["a", "b", "c"]);
    expect(parsed.rows).toEqual([
      ["1", "2", "3"],
      ["4", "5", "6"],
    ]);
    expect(parsed.totalRows).toBe(2);
    expect(parsed.totalCols).toBe(3);
    expect(parsed.truncatedText).toBe(false);
  });

  it("handles quotes, doubled quotes, embedded delimiters and newlines", () => {
    const parsed = parseDelimited(
      'name,note\r\n"Smith, J","said ""hi""\nthen left"\r\nplain,x\r\n',
    );
    expect(parsed.rows).toEqual([
      ["Smith, J", 'said "hi"\nthen left'],
      ["plain", "x"],
    ]);
  });

  it("uses the tab delimiter for tsv", () => {
    expect(delimiterForFilename("rows.tsv")).toBe("\t");
    expect(delimiterForFilename("rows.csv")).toBe(",");
    expect(parseDelimited("a\tb\n1\t2\n", "\t").rows).toEqual([["1", "2"]]);
  });

  it("caps rows and columns while reporting totals", () => {
    const header = Array.from({ length: 60 }, (_, i) => `c${i}`).join(",");
    const row = Array.from({ length: 60 }, (_, i) => String(i)).join(",");
    const text = [header, ...Array.from({ length: 700 }, () => row)].join("\n");
    const parsed = parseDelimited(text);
    expect(parsed.header).toHaveLength(50);
    expect(parsed.rows).toHaveLength(500);
    expect(parsed.rows[0]).toHaveLength(50);
    expect(parsed.totalRows).toBe(700);
    expect(parsed.totalCols).toBe(60);
  });

  it("cuts at the character cap and drops the partial last record", () => {
    const parsed = parseDelimited("a,b\n1,2\n3,4\n5,6", ",", { maxChars: 11 });
    expect(parsed.truncatedText).toBe(true);
    expect(parsed.rows).toEqual([["1", "2"]]);
  });

  it("pads short rows to the column count", () => {
    const parsed = parseDelimited("a,b,c\n1\n");
    expect(parsed.rows).toEqual([["1", "", ""]]);
  });
});

describe("isNumericColumn", () => {
  it("detects numbers, currency, percentages and thousands separators", () => {
    const rows = [
      ["AMER", "9,204,100", "3.1%", "$1.50", ""],
      ["EMEA", "4812400", "-17.3%", "$0.25", "x"],
    ];
    expect(isNumericColumn(rows, 0)).toBe(false);
    expect(isNumericColumn(rows, 1)).toBe(true);
    expect(isNumericColumn(rows, 2)).toBe(true);
    expect(isNumericColumn(rows, 3)).toBe(true);
    expect(isNumericColumn(rows, 4)).toBe(false);
    // An all-empty column is not numeric.
    expect(isNumericColumn([["", ""]], 1)).toBe(false);
  });
});

describe("ChatCsvPreview", () => {
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

  it("renders a sticky-header table with numeric right alignment and a footer", async () => {
    const onDownload = vi.fn();
    await act(async () => {
      root.render(
        <ChatCsvPreview
          text={"region,revenue\nAMER,9204100\nEMEA,4812400\n"}
          filename="rows.csv"
          onDownload={onDownload}
        />,
      );
    });
    const table = container.querySelector("table");
    expect(table?.querySelector("thead")?.className).toContain("sticky");
    const headers = [...(table?.querySelectorAll("th") ?? [])];
    expect(headers.map((th) => th.textContent)).toEqual(["region", "revenue"]);
    expect(headers[0].className).toContain("text-left");
    expect(headers[1].className).toContain("text-right");
    expect(table?.querySelectorAll("tbody tr")).toHaveLength(2);
    expect(
      container.querySelector('[data-testid="chat-csv-preview-footer"]')?.textContent,
    ).toContain("Showing 2 of 2 rows");
    const download = container.querySelector<HTMLButtonElement>(
      '[data-testid="chat-csv-preview-download"]',
    );
    await act(async () => download?.click());
    expect(onDownload).toHaveBeenCalledTimes(1);
  });

  it("reports the row cap in the footer", async () => {
    const text = ["n", ...Array.from({ length: 800 }, (_, i) => String(i))].join("\n");
    await act(async () => {
      root.render(<ChatCsvPreview text={text} filename="n.csv" />);
    });
    expect(
      container.querySelector('[data-testid="chat-csv-preview-footer"]')?.textContent,
    ).toContain("Showing 500 of 800 rows");
    expect(container.querySelector('[data-testid="chat-csv-preview-download"]')).toBeNull();
  });
});
