import { act } from "react";
import { createRoot, type Root } from "react-dom/client";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { toCsv } from "~/lib/chat-run-steps";
import { DataTable, compareCells, inferColumnType, sortRows } from "./data-table";

(
  globalThis as typeof globalThis & { IS_REACT_ACT_ENVIRONMENT: boolean }
).IS_REACT_ACT_ENVIRONMENT = true;

const columns = [
  { name: "region", type: "string" },
  { name: "revenue", type: "decimal" },
  { name: "active" },
];
const rows: unknown[][] = [
  ["EMEA", 200.5, true],
  ["AMER", null, false],
  ["APAC", 30, null],
  ["LATAM", 1000, true],
];

const q = (root: ParentNode, selector: string) => root.querySelector(selector);
const qa = (root: ParentNode, selector: string) => [...root.querySelectorAll(selector)];

function firstColumnCells(container: ParentNode): string[] {
  return qa(container, "tbody tr").map(
    (tr) => tr.querySelectorAll("td")[1]?.textContent ?? "",
  );
}

describe("DataTable helpers", () => {
  it("infers a column type from the first rows when none is given", () => {
    expect(inferColumnType({ name: "active" }, rows, 2)).toBe("boolean");
    expect(inferColumnType({ name: "n" }, [[1], [2]], 0)).toBe("number");
    expect(inferColumnType({ name: "m" }, [[1], ["x"]], 0)).toBe("string");
    expect(inferColumnType({ name: "typed", type: "uuid" }, rows, 0)).toBe("uuid");
    expect(inferColumnType({ name: "empty" }, [[null]], 0)).toBe("unknown");
  });
  it("compares numerically and puts nulls last in both directions", () => {
    expect(compareCells(2, 10, "asc")).toBeLessThan(0);
    expect(compareCells("2", "10", "asc")).toBeLessThan(0);
    expect(compareCells(null, 1, "asc")).toBeGreaterThan(0);
    expect(compareCells(null, 1, "desc")).toBeGreaterThan(0);
    expect(compareCells("b", "a", "desc")).toBeLessThan(0);
  });
  it("sorts stably", () => {
    const tied: unknown[][] = [["a", 1], ["b", 1], ["c", 0]];
    expect(sortRows(tied, { col: 1, dir: "asc" }).map((row) => row[0])).toEqual(["c", "a", "b"]);
    expect(sortRows(tied, { col: 1, dir: "desc" }).map((row) => row[0])).toEqual(["a", "b", "c"]);
    expect(sortRows(tied, null)).toBe(tied);
  });
});

describe("DataTable", () => {
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
  const render = async (props: Partial<Parameters<typeof DataTable>[0]> = {}) => {
    await act(async () => {
      root.render(<DataTable columns={columns} rows={rows} totalRows={rows.length} {...props} />);
    });
  };

  it("renders every row with a gutter, typed header dots and dim nulls", async () => {
    await render();
    expect(q(container, '[data-testid="chat-data-table"]')).not.toBeNull();
    expect(qa(container, "tbody tr")).toHaveLength(4);
    expect(qa(container, "tbody tr")[3].querySelector("td")?.textContent).toBe("4");
    expect(qa(container, "thead th")).toHaveLength(4);
    const nulls = qa(container, "tbody td span.italic");
    expect(nulls).toHaveLength(2);
    expect(nulls[0].textContent).toBe("null");
    // Boolean cells are mono; the revenue column is right-aligned.
    expect(qa(container, "tbody tr")[0].querySelectorAll("td")[3].textContent).toBe("true");
    expect(
      qa(container, "tbody tr")[0].querySelectorAll("td")[2].className,
    ).toContain("text-right");
    expect(q(container, "thead")?.className).toContain("sticky");
  });

  it("cycles a numeric sort asc → desc → none with nulls last", async () => {
    await render();
    const button = q(container, '[data-testid="chat-data-table-sort-revenue"]') as HTMLButtonElement;
    await act(async () => button.click());
    expect(firstColumnCells(container)).toEqual(["APAC", "EMEA", "LATAM", "AMER"]);
    expect(button.closest("th")?.getAttribute("aria-sort")).toBe("ascending");
    await act(async () => button.click());
    expect(firstColumnCells(container)).toEqual(["LATAM", "EMEA", "APAC", "AMER"]);
    expect(button.closest("th")?.getAttribute("aria-sort")).toBe("descending");
    await act(async () => button.click());
    expect(firstColumnCells(container)).toEqual(["EMEA", "AMER", "APAC", "LATAM"]);
    expect(button.closest("th")?.getAttribute("aria-sort")).toBe("none");
  });

  it("shows a load-all button only when more rows exist and calls back", async () => {
    await render();
    expect(q(container, '[data-testid="chat-data-table-load-all"]')).toBeNull();
    const onLoadAll = vi.fn();
    await render({ totalRows: 1_204, onLoadAll });
    const button = q(container, '[data-testid="chat-data-table-load-all"]') as HTMLButtonElement;
    expect(button.textContent).toContain("Load all 1,204 rows");
    await act(async () => button.click());
    expect(onLoadAll).toHaveBeenCalledTimes(1);
    await render({ totalRows: 1_204, onLoadAll, loadingAll: true });
    expect(
      (q(container, '[data-testid="chat-data-table-load-all"]') as HTMLButtonElement).disabled,
    ).toBe(true);
  });

  it("windows long results by 200 rows and grows the viewport past 50", async () => {
    const many = Array.from({ length: 450 }, (_, i) => [`r${i}`, i, i % 2 === 0]);
    await render({ rows: many, totalRows: many.length });
    expect(qa(container, "tbody tr")).toHaveLength(200);
    expect(q(container, '[data-testid="chat-data-table"] > div')?.className).toContain(
      "max-h-[32rem]",
    );
    const next = q(container, '[data-testid="chat-data-table-show-next"]') as HTMLButtonElement;
    expect(next.textContent).toContain("Show next 200");
    await act(async () => next.click());
    expect(qa(container, "tbody tr")).toHaveLength(400);
    await act(async () => next.click());
    expect(qa(container, "tbody tr")).toHaveLength(450);
    expect(q(container, '[data-testid="chat-data-table-show-next"]')).toBeNull();
  });

  it("truncates object cells and staggers only the first paint", async () => {
    const wide = { key: "x".repeat(120) };
    await render({ rows: [[wide, 1, true]], columns: [{ name: "obj" }, ...columns.slice(1)] });
    const cell = qa(container, "tbody tr")[0].querySelectorAll("td")[1].querySelector("span");
    expect(cell?.textContent?.length).toBe(81);
    expect(cell?.getAttribute("title")).toBe(JSON.stringify(wide));
    expect(qa(container, "tbody tr")[0].className).toContain("chat-tool-rows-in");
  });

  it("round-trips the visible rows through toCsv", () => {
    const csv = toCsv(
      columns.map((column) => column.name),
      rows,
    );
    expect(csv.split("\n")[0]).toBe("region,revenue,active");
    expect(csv.split("\n")[2]).toBe("AMER,,false");
    expect(csv.split("\n")).toHaveLength(5);
  });
});
