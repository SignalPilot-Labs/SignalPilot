import { chipStat, kindForTool, normalizeToolName, parsePlan, parseRows, presentLabel, shortLabel } from "../src/tool-meta";

describe("tool-meta", () => {
  it("strips the MCP server prefix", () => {
    expect(normalizeToolName("mcp__signalpilot__query_database")).toBe("query_database");
    expect(normalizeToolName("mcp__claude_ai_anth__list_tables")).toBe("list_tables");
    expect(normalizeToolName("Bash")).toBe("Bash");
  });

  it("classifies tools into card families", () => {
    expect(kindForTool("query_database")).toBe("table");
    expect(kindForTool("list_tables")).toBe("table_list");
    expect(kindForTool("explore_columns")).toBe("schema");
    expect(kindForTool("validate_sql")).toBe("validation");
    expect(kindForTool("verify_model_values")).toBe("validation");
    expect(kindForTool("dbt_execute")).toBe("dbt_run");
    expect(kindForTool("sandbox_exec")).toBe("terminal");
    expect(kindForTool("search_knowledge")).toBe("knowledge");
    expect(kindForTool("Write")).toBe("file");
    expect(kindForTool("TodoWrite")).toBe("plan");
    expect(kindForTool("WebSearch")).toBe("web");
    expect(kindForTool("Agent")).toBe("subagent");
    expect(kindForTool("something_new")).toBe("generic");
  });

  it("gives every tool a present-tense line", () => {
    expect(presentLabel("query_database")).toBe("Querying the warehouse");
    expect(presentLabel("custom_tool")).toBe("Running custom tool");
  });

  it("shortens labels at word boundaries", () => {
    expect(shortLabel("Checking the date range of rpt_daily_profitability.")).toBe("Checking the date range of…");
    expect(shortLabel("Short one")).toBe("Short one");
  });

  it("parses rows, plans and chip stats", () => {
    expect(parseRows("1,204 rows · 0.4 s")).toBe(1204);
    expect(parseRows("1 row")).toBe(1);
    expect(parseRows("No issues")).toBeNull();
    expect(parsePlan("Plan updated · 2/5 done")).toEqual({ done: 2, total: 5 });
    expect(parsePlan("Plan updated")).toBeNull();
    expect(chipStat("42 tables\nmore detail")).toBe("42 tables");
    expect(chipStat("A very long summary that keeps going")).toBe("A very long summary tha…");
    expect(chipStat(null)).toBe("");
  });
});
