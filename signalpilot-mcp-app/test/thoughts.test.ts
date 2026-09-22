import { headlineFrom, recentThoughts, stripMarkdown } from "../src/thoughts";

describe("thoughts", () => {
  it("drops code fences, tables, headings and rules", () => {
    const md = "# Title\n\nSome prose here.\n\n```sql\nselect 1\n```\n\n| a | b |\n|---|---|\n| 1 | 2 |\n\n---\n\nMore prose **bold** and `code` and [link](https://x).";
    expect(stripMarkdown(md)).toBe("Some prose here.\nMore prose bold and code and link.");
  });

  it("keeps snake_case identifiers while stripping real emphasis", () => {
    expect(stripMarkdown("rpt_daily_profitability has _both_ booked_at and **invoiced_at**.")).toBe(
      "rpt_daily_profitability has both booked_at and invoiced_at.",
    );
  });

  it("keeps the last three sentence fragments", () => {
    expect(recentThoughts("One sentence here. Two sentence here! Three sentence here? Four sentence here. Five is last")).toEqual([
      { id: 2, text: "Three sentence here?" },
      { id: 3, text: "Four sentence here." },
      { id: 4, text: "Five is last" },
    ]);
  });

  it("ignores fragments that are too short to read", () => {
    expect(recentThoughts("Ok. Yes. This one is long enough to show.")).toEqual([{ id: 0, text: "This one is long enough to show." }]);
  });

  it("builds a headline from the first readable sentence", () => {
    expect(headlineFrom("## Result\n\n- Q3 margin was 37.8%. Second sentence.")).toBe("Q3 margin was 37.8%.");
    expect(headlineFrom("```\ncode only\n```")).toBeNull();
    expect(headlineFrom(`${"x".repeat(200)} tail`, 20)?.length).toBe(20);
  });
});
