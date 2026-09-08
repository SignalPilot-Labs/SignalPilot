import { describe, expect, it } from "vitest";

import { datasetFileRefs, inlineDatasets, parseDatasetText } from "./datasets";
import type { DashboardSpec } from "./schema";

describe("parseDatasetText", () => {
  it("parses CSV with a header, numeric coercion and empty cells", () => {
    const rows = parseDatasetText('a,b,c\n1,x,\n2.5,"y, z",true\n-3e2,"q""uote",0\n', "artifacts/x.csv");
    expect(rows).toEqual([
      { a: 1, b: "x", c: null },
      { a: 2.5, b: "y, z", c: "true" },
      { a: -300, b: 'q"uote', c: 0 },
    ]);
  });

  it("parses TSV and CRLF line endings", () => {
    const rows = parseDatasetText("a\tb\r\n1\thello world\r\n", "artifacts/x.tsv");
    expect(rows).toEqual([{ a: 1, b: "hello world" }]);
  });

  it("strips a UTF-8 BOM and fills short records with null", () => {
    const rows = parseDatasetText("﻿a,b\n1\n", "artifacts/x.csv");
    expect(rows).toEqual([{ a: 1, b: null }]);
  });

  it("keeps quoted numeric-looking strings as numbers only when fully numeric", () => {
    const rows = parseDatasetText("id,code\n1,007\n2,12ab\n", "artifacts/x.csv");
    expect(rows).toEqual([
      { id: 1, code: 7 },
      { id: 2, code: "12ab" },
    ]);
  });

  it("coerces the numeric forms Python float() reads, and only those", () => {
    const rows = parseDatasetText("a,b,c,d,e\n+5,5.,1_000,inf,1e3\n", "artifacts/x.csv");
    // "1_000" and "inf" are numbers in Python; the TS side keeps them as text (documented drift).
    expect(rows).toEqual([{ a: 5, b: 5, c: "1_000", d: "inf", e: 1000 }]);
  });

  it("keeps empty header names as \"\" and skips all-blank records", () => {
    const rows = parseDatasetText("a,,b\n1,2,3\n , ,\n,,\n4,5,6\n", "artifacts/x.csv");
    expect(rows).toEqual([
      { a: 1, "": 2, b: 3 },
      { a: 4, "": 5, b: 6 },
    ]);
  });

  it("parses JSON arrays of objects", () => {
    const rows = parseDatasetText('[{"a":1,"b":"x","c":null,"d":true}]', "artifacts/x.json");
    expect(rows).toEqual([{ a: 1, b: "x", c: null, d: true }]);
  });

  it("throws on invalid JSON or non-array JSON", () => {
    expect(() => parseDatasetText("{", "artifacts/x.json")).toThrow(/invalid JSON/);
    expect(() => parseDatasetText('{"a":1}', "artifacts/x.json")).toThrow(/array of objects/);
    expect(() => parseDatasetText("[1]", "artifacts/x.json")).toThrow(/row 0/);
  });

  it("returns no rows for empty text", () => {
    expect(parseDatasetText("", "artifacts/x.csv")).toEqual([]);
  });
});

describe("datasetFileRefs / inlineDatasets", () => {
  const spec = {
    version: 1,
    title: "T",
    datasets: {
      a: { file: "artifacts/a.csv" },
      b: { rows: [{ x: 1 }] },
      c: { file: "artifacts/c.json" },
    },
    charts: [],
  } as unknown as DashboardSpec;

  it("lists file-backed datasets in order", () => {
    expect(datasetFileRefs(spec)).toEqual([
      { name: "a", path: "artifacts/a.csv" },
      { name: "c", path: "artifacts/c.json" },
    ]);
  });

  it("collects inline rows", () => {
    expect(inlineDatasets(spec)).toEqual({ b: [{ x: 1 }] });
  });
});
