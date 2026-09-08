import { describe, expect, it } from "vitest";

import { datasetFileRefs, datasetSnapshotPath, inlineDatasets, parseDatasetCsv } from "./datasets";
import type { DashboardSpec } from "./schema";

describe("parseDatasetCsv", () => {
  it("parses a header, numeric coercion and empty cells", () => {
    const rows = parseDatasetCsv('a,b,c\n1,x,\n2.5,"y, z",true\n-3e2,"q""uote",0\n');
    expect(rows).toEqual([
      { a: 1, b: "x", c: null },
      { a: 2.5, b: "y, z", c: "true" },
      { a: -300, b: 'q"uote', c: 0 },
    ]);
  });

  it("accepts CRLF line endings", () => {
    expect(parseDatasetCsv("a,b\r\n1,hello world\r\n")).toEqual([{ a: 1, b: "hello world" }]);
  });

  it("strips a UTF-8 BOM and fills short records with null", () => {
    expect(parseDatasetCsv("﻿a,b\n1\n")).toEqual([{ a: 1, b: null }]);
  });

  it("coerces cells to numbers only when fully numeric", () => {
    expect(parseDatasetCsv("id,code\n1,007\n2,12ab\n")).toEqual([
      { id: 1, code: 7 },
      { id: 2, code: "12ab" },
    ]);
  });

  it("coerces the numeric forms Python float() reads, and only those", () => {
    // "1_000" and "inf" are numbers in Python; the TS side keeps them as text (documented drift).
    expect(parseDatasetCsv("a,b,c,d,e\n+5,5.,1_000,inf,1e3\n")).toEqual([
      { a: 5, b: 5, c: "1_000", d: "inf", e: 1000 },
    ]);
  });

  it('keeps empty header names as "" and skips all-blank records', () => {
    expect(parseDatasetCsv("a,,b\n1,2,3\n , ,\n,,\n4,5,6\n")).toEqual([
      { a: 1, "": 2, b: 3 },
      { a: 4, "": 5, b: 6 },
    ]);
  });

  it("does not split on tabs", () => {
    expect(parseDatasetCsv("a\tb\n1\t2\n")).toEqual([{ "a\tb": "1\t2" }]);
  });

  it("returns no rows for empty text", () => {
    expect(parseDatasetCsv("")).toEqual([]);
  });
});

describe("datasetFileRefs / inlineDatasets", () => {
  const spec = {
    version: 1,
    title: "T",
    datasets: {
      a: { connection: "warehouse", sql: "select 1 as x" },
      b: { rows: [{ x: 1 }] },
      c: { connection: "duck", sql: "select 2 as x" },
    },
    charts: [],
  } as unknown as DashboardSpec;

  it("builds the snapshot path from the dataset name", () => {
    expect(datasetSnapshotPath("monthly")).toBe("artifacts/datasets/monthly.csv");
  });

  it("lists SQL datasets in order with their snapshot paths", () => {
    expect(datasetFileRefs(spec)).toEqual([
      { name: "a", path: "artifacts/datasets/a.csv" },
      { name: "c", path: "artifacts/datasets/c.csv" },
    ]);
  });

  it("collects the static rows", () => {
    expect(inlineDatasets(spec)).toEqual({ b: [{ x: 1 }] });
  });
});
