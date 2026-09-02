import { describe, expect, it } from "vitest";
import { parseToolResult, toolResultKindForTool } from "~/lib/chat-run-steps";
import {
  fixtureColumnProfileCompletion,
  fixtureConnectorJsonCompletion,
  fixtureDbtRunCompletion,
  fixtureKnowledgeCompletion,
  fixtureSchemaCompletion,
  fixtureTableCompletion,
  fixtureTableListCompletion,
  fixtureTerminalCompletion,
  fixtureValidationFailureCompletion,
} from "~/lib/chat-test-fixture-tools";

describe("parseToolResult", () => {
  it("parses a structured table with its counts and redaction", () => {
    const result = parseToolResult(fixtureTableCompletion("t4"), "query_database", false);
    expect(result.kind).toBe("table");
    if (result.kind !== "table") return;
    expect(result.columns).toHaveLength(8);
    expect(result.columns[2]).toEqual({ name: "email", logicalType: "string" });
    expect(result.rows).toHaveLength(50);
    expect(result.rowCount).toBe(1_204);
    expect(result.queryRowCount).toBe(1_204);
    expect(result.executionMs).toBe(312);
    expect(result.resultId).toBe("res-31");
    expect(result.previewTruncated).toBe(true);
    expect(result.completeness).toBe("complete");
    expect(result.piiRedactedColumns).toEqual(["email"]);
    expect(result.source).toBe("structured");
    expect(result.summary).toBe("Preview 50 of 1,204 rows · 312 ms");
    expect(result.resultText).toContain("[1204 rows, 312ms");
    expect(result.resultChars).toBeGreaterThan(0);
    expect(result.errorMessage).toBeNull();
  });

  it("parses a table list with schemas and key chips", () => {
    const result = parseToolResult(fixtureTableListCompletion("t13"), "list_tables", false);
    expect(result.kind).toBe("table_list");
    if (result.kind !== "table_list") return;
    expect(result.total).toBe(47);
    expect(result.entries).toHaveLength(47);
    expect(result.databases.map((db) => db.name)).toEqual(["analytics", "staging", "raw"]);
    const orders = result.entries.find((entry) => entry.name === "analytics.fct_orders");
    expect(orders?.columns[0]).toEqual({ name: "order_id", primaryKey: true, references: null });
    expect(orders?.columns[1].references).toBe("dim_customers.customer_id");
    expect(orders?.rowCount).toBeGreaterThan(0);
    expect(result.dbType).toBe("postgres");
  });

  it("parses a schema with keys, references and samples", () => {
    const result = parseToolResult(fixtureSchemaCompletion("t2"), "get_table_schema", false);
    expect(result.kind).toBe("schema");
    if (result.kind !== "schema") return;
    expect(result.table).toBe("analytics.fct_orders");
    expect(result.columns).toHaveLength(18);
    expect(result.columns[0].primaryKey).toBe(true);
    expect(result.columns[1].foreignKey).toBe("analytics.dim_customers.customer_id");
    expect(result.columns[3].pii).toBe("email");
    expect(result.rowCount).toBe(2_143_882);
    expect(result.foreignKeys).toHaveLength(2);
    expect(result.referencedBy[0].referencesColumn).toBe("order_id");
    expect(result.sampleValues.tier).toEqual(["enterprise", "mid-market", "smb"]);
  });

  it("parses a column profile with stats and top values", () => {
    const result = parseToolResult(fixtureColumnProfileCompletion("t14"), "explore_columns", false);
    expect(result.kind).toBe("column_profile");
    if (result.kind !== "column_profile") return;
    expect(result.columns).toHaveLength(4);
    expect(result.columns[0].distinctCount).toBe(3);
    expect(result.columns[0].topValues[0]).toEqual({ value: "1", count: 1_221_408 });
    expect(result.columns[2].nullPct).toBe(2.9);
    expect(result.columns[2].sampleValues).toContain("marketplace");
    expect(result.columns[1].avg).toBe("7,512.40");
  });

  it("keeps the kind on an error payload and surfaces the sanitized message", () => {
    const result = parseToolResult(fixtureValidationFailureCompletion("t3"), "validate_sql", true);
    expect(result.kind).toBe("validation");
    if (result.kind !== "validation") return;
    expect(result.valid).toBe(false);
    expect(result.suggestedFix).toContain("dim_regions");
    expect(result.checks).toEqual(["syntax", "column references"]);
    expect(result.errorMessage).toContain('column "region_name" does not exist');
    expect(result.summary).toContain("does not exist");
  });

  it("parses a dbt run with statuses, failures and the log tail", () => {
    const result = parseToolResult(fixtureDbtRunCompletion("t15"), "dbt_execute", false);
    expect(result.kind).toBe("dbt_run");
    if (result.kind !== "dbt_run") return;
    expect(result.statuses).toEqual({ success: 12, error: 1 });
    expect(result.total).toBe(13);
    expect(result.failures[0].node).toBe("model.analytics.rpt_region_rollup");
    expect(result.elapsedS).toBe(8.4);
    expect(result.exitCode).toBe(1);
    expect(result.log).toContain("PASS=12");
    expect(result.command).toBe("dbt run --select marts.revenue+");
  });

  it("parses a terminal result", () => {
    const result = parseToolResult(fixtureTerminalCompletion("t7"), "Bash", false);
    expect(result.kind).toBe("terminal");
    if (result.kind !== "terminal") return;
    expect(result.exitCode).toBe(0);
    expect(result.stdout).toContain("growth sums to 51.9");
    expect(result.stderr).toBe("");
    expect(result.command).toBe("python analysis/q3_growth.py --check");
  });

  it("parses knowledge docs", () => {
    const result = parseToolResult(fixtureKnowledgeCompletion("t16"), "search_knowledge", false);
    expect(result.kind).toBe("knowledge");
    if (result.kind !== "knowledge") return;
    expect(result.mode).toBe("search");
    expect(result.docs).toHaveLength(3);
    expect(result.docs[1]).toMatchObject({ id: "kb-207", scope: "project", title: "Region dimension join" });
    expect(result.total).toBe(3);
  });

  it("parses an artifact result", () => {
    const result = parseToolResult(
      {
        tool_call_id: "t11",
        error: false,
        summary: "Published q3_revenue_by_region.csv",
        result: { kind: "artifact", artifact_kind: "table", published: true, filename: "q3.csv", artifact_index: 0 },
      },
      "publish_table",
      false,
    );
    expect(result).toMatchObject({ kind: "artifact", artifactKind: "table", published: true, filename: "q3.csv", artifactIndex: 0 });
  });

  it("passes a json value through untouched", () => {
    const result = parseToolResult(fixtureConnectorJsonCompletion("t17"), "search_contacts", false);
    expect(result.kind).toBe("json");
    if (result.kind !== "json") return;
    expect((result.value as { total: number }).total).toBe(2);
  });

  it("maps a text kind and falls back to text when only result_text exists", () => {
    expect(
      parseToolResult({ error: false, summary: "ok", result: { kind: "text" }, result_text: "hello" }, "x", false),
    ).toMatchObject({ kind: "text", summary: "ok", resultText: "hello" });
    expect(
      parseToolResult({ error: false, summary: "The tool completed.", result_text: "raw body" }, "x", false),
    ).toMatchObject({ kind: "text", summary: null, resultText: "raw body" });
  });

  it("keeps an unknown kind as json with the raw object", () => {
    const result = parseToolResult(
      { error: false, summary: "?", result: { kind: "hologram", shape: "cube" } },
      "x",
      false,
    );
    expect(result).toMatchObject({ kind: "json", value: { kind: "hologram", shape: "cube" } });
  });

  it("folds a pre-projector completion to legacy with a null placeholder summary", () => {
    const legacy = parseToolResult(
      { tool_call_id: "t1", summary: "The tool completed.", error: false },
      "TodoWrite",
      false,
    );
    expect(legacy).toEqual({
      kind: "legacy",
      summary: null,
      resultText: null,
      resultChars: null,
      truncated: false,
      errorMessage: null,
    });
    const failed = parseToolResult(
      { summary: "The governed tool returned an error.", error: true },
      "query_database",
      true,
    );
    expect(failed.kind).toBe("legacy");
    expect(failed.summary).toBeNull();
    expect(failed.errorMessage).toBeNull();
    expect(
      parseToolResult({ summary: "boom", error: true, message: "ignored" }, "x", true).errorMessage,
    ).toBe("boom");
    expect(
      parseToolResult({ error: true, error_message: "connection refused" }, "x", true).errorMessage,
    ).toBe("connection refused");
  });

  it("turns a legacy validate_sql completion into a validation from the error flag", () => {
    const ok = parseToolResult({ summary: "The tool completed.", error: false }, "validate_sql", false);
    expect(ok).toMatchObject({ kind: "validation", valid: true, message: null });
    const bad = parseToolResult(
      { summary: "syntax error at end of input", error: true },
      "mcp__signalpilot__validate_sql",
      true,
    );
    expect(bad).toMatchObject({ kind: "validation", valid: false, message: "syntax error at end of input" });
  });

  it("never throws on malformed shapes", () => {
    const cases: Record<string, unknown>[] = [
      { result: { kind: "table", columns: "nope", rows: [1, "x", null, [undefined, {}]] } },
      { result: { kind: "table_list", entries: [null, 3, { columns: "x" }], databases: {} } },
      { result: { kind: "schema", columns: [{ name: 4 }], sample_values: [1, 2], foreign_keys: "x" } },
      { result: { kind: "column_profile", columns: [{ top_values: [null] }] } },
      { result: { kind: "dbt_run", statuses: [1, 2], failures: "x", exit_code: "1" } },
      { result: { kind: "knowledge", docs: 7, mode: 42 } },
      { result: { kind: "artifact", artifact_kind: "hologram" } },
      { result: { kind: "validation", valid: "yes", checks: [1, "a"] } },
      { result: "just a string", summary: 12, result_text: [] },
      { result: [], result_chars: Number.NaN, truncated: "true" },
    ];
    for (const payload of cases) {
      expect(() => parseToolResult(payload, "x", false)).not.toThrow();
    }
    const table = parseToolResult(cases[0], "query_database", false);
    expect(table.kind).toBe("table");
    if (table.kind === "table") {
      expect(table.columns).toEqual([]);
      expect(table.rows).toEqual([[], [], [], [null, null]]);
      expect(table.previewRowCount).toBe(4);
    }
    const dbt = parseToolResult(cases[4], "dbt_execute", false);
    expect(dbt).toMatchObject({ kind: "dbt_run", statuses: {}, failures: [], exitCode: null, total: 0 });
    expect(parseToolResult(cases[9], "x", false)).toMatchObject({ kind: "legacy", resultChars: null, truncated: false });
  });
});

describe("toolResultKindForTool", () => {
  it("maps tools to the result kind their card expects", () => {
    expect(toolResultKindForTool("query_database")).toBe("table");
    expect(toolResultKindForTool("list_tables")).toBe("table_list");
    expect(toolResultKindForTool("get_table_schema")).toBe("schema");
    expect(toolResultKindForTool("explore_columns")).toBe("column_profile");
    expect(toolResultKindForTool("validate_sql")).toBe("validation");
    expect(toolResultKindForTool("verify_model_values")).toBe("validation");
    expect(toolResultKindForTool("dbt_execute")).toBe("dbt_run");
    expect(toolResultKindForTool("Bash")).toBe("terminal");
    expect(toolResultKindForTool("search_knowledge")).toBe("knowledge");
    expect(toolResultKindForTool("publish_chart")).toBe("artifact");
    expect(toolResultKindForTool("start_analysis_notebook")).toBe("artifact");
    expect(toolResultKindForTool("run_cells")).toBe("json");
    expect(toolResultKindForTool("TodoWrite")).toBeNull();
    expect(toolResultKindForTool("Read")).toBeNull();
  });
});
