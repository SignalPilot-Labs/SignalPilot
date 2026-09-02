import type { ToolCompletedPayload, ToolResult } from "~/lib/api";
import type { FixtureEvent } from "./chat-test-fixture-data";

/**
 * `tool_completed` payload builders for the /chats/test fixture. One per
 * wire result kind, with realistic data so every tool card variant can be
 * exercised by the replay. Import these from lib/chat-test-fixture-data.ts.
 */

type Cell = string | number | boolean | null;

/** The governed query's saved result id (shared with the publish steps). */
export const FIXTURE_QUERY_RESULT_ID = "res-31";
export const FIXTURE_QUERY_ROW_COUNT = 1_204;

export const FIXTURE_QUERY_COLUMNS: { name: string; logical_type: string }[] = [
  { name: "order_id", logical_type: "string" },
  { name: "region", logical_type: "string" },
  { name: "email", logical_type: "string" },
  { name: "order_quarter", logical_type: "string" },
  { name: "tier", logical_type: "string" },
  { name: "net_revenue", logical_type: "decimal" },
  { name: "order_count", logical_type: "integer" },
  { name: "growth_pct", logical_type: "decimal" },
];

const REGIONS = ["AMER", "EMEA", "APAC"];
const TIERS = ["enterprise", "mid-market", "smb", "marketplace"];

/** Small deterministic PRNG so replayed rows are identical on every frame. */
function noise(index: number, salt: number): number {
  let x = (index + 1) * 2_654_435_761 + salt * 40_503;
  x ^= x >>> 15;
  x = Math.imul(x, 2_246_822_519);
  x ^= x >>> 13;
  x = Math.imul(x, 3_266_489_917);
  x ^= x >>> 16;
  return (x >>> 0) / 4_294_967_296;
}

/** One generated result row; `index` is the 0-based position in the result. */
export function fixtureQueryRow(index: number): Cell[] {
  const region = REGIONS[index % REGIONS.length];
  const tier = TIERS[Math.floor(noise(index, 1) * TIERS.length)];
  const quarter = noise(index, 2) < 0.48 ? "2025-Q2" : "2025-Q3";
  const revenue = Math.round((900 + noise(index, 3) * 48_000) * 100) / 100;
  const orders = 1 + Math.floor(noise(index, 4) * 14);
  const growth = Math.round((noise(index, 5) * 60 - 12) * 10) / 10;
  return [
    `ORD-${100_001 + index}`,
    region,
    "[REDACTED]",
    quarter,
    tier,
    revenue,
    orders,
    index % 37 === 0 ? null : growth,
  ];
}

/**
 * Pages the full 1,204-row result the way the gateway route does. Used by
 * the harness's `getToolResultRows` stub for `"res-31"`.
 */
export function fixtureQueryResultPage(offset = 0, limit = 500) {
  const start = Math.max(0, Math.min(offset, FIXTURE_QUERY_ROW_COUNT));
  const end = Math.min(FIXTURE_QUERY_ROW_COUNT, start + Math.max(0, limit));
  const rows: Cell[][] = [];
  for (let index = start; index < end; index += 1) {
    rows.push(fixtureQueryRow(index));
  }
  return {
    result_id: FIXTURE_QUERY_RESULT_ID,
    execution_id: "exec-fixture-1",
    columns: FIXTURE_QUERY_COLUMNS,
    rows,
    offset: start,
    limit,
    saved_row_count: FIXTURE_QUERY_ROW_COUNT,
    query_row_count: FIXTURE_QUERY_ROW_COUNT,
    completeness: "complete",
    truncation_reason: null,
    connection_name: "warehouse_prod",
  };
}

function completed(
  toolCallId: string,
  tool: string,
  summary: string,
  result: ToolResult,
  resultText: string,
  extra: Partial<ToolCompletedPayload> = {},
): ToolCompletedPayload & Record<string, unknown> {
  return {
    tool_call_id: toolCallId,
    tool,
    error: false,
    summary,
    result,
    result_text: resultText,
    result_chars: resultText.length,
    truncated: false,
    v: 1,
    ...extra,
  };
}

// --- t2: get_table_schema → schema ------------------------------------------

const FCT_ORDERS_COLUMNS: {
  name: string;
  type: string;
  nullable: boolean;
  primary_key?: boolean;
  foreign_key?: string;
  comment?: string;
  pii?: string;
}[] = [
  { name: "order_id", type: "varchar", nullable: false, primary_key: true, comment: "Order surrogate key" },
  { name: "customer_id", type: "varchar", nullable: false, foreign_key: "analytics.dim_customers.customer_id" },
  { name: "region_id", type: "integer", nullable: false, foreign_key: "analytics.dim_regions.region_id" },
  { name: "email", type: "varchar", nullable: true, pii: "email" },
  { name: "order_date", type: "date", nullable: false },
  { name: "order_quarter", type: "varchar", nullable: false, comment: "'2025-Q3' style label" },
  { name: "tier", type: "varchar", nullable: true },
  { name: "channel", type: "varchar", nullable: true },
  { name: "currency", type: "varchar", nullable: false },
  { name: "gross_revenue", type: "numeric(18,2)", nullable: false },
  { name: "discount_amount", type: "numeric(18,2)", nullable: false },
  { name: "refund_amount", type: "numeric(18,2)", nullable: true },
  { name: "net_revenue", type: "numeric(18,2)", nullable: false, comment: "gross - discount - refunds after close" },
  { name: "item_count", type: "integer", nullable: false },
  { name: "is_first_order", type: "boolean", nullable: false },
  { name: "fulfilled_at", type: "timestamp", nullable: true },
  { name: "updated_at", type: "timestamp", nullable: false },
  { name: "_loaded_at", type: "timestamp", nullable: false, comment: "dbt load timestamp" },
];

export function fixtureSchemaCompletion(toolCallId: string) {
  const text = FCT_ORDERS_COLUMNS.map(
    (column) =>
      `${column.primary_key ? "*" : ""}${column.name}: ${column.type}${column.nullable ? "" : " not null"}`,
  ).join("\n");
  return completed(
    toolCallId,
    "mcp__signalpilot__get_table_schema",
    "analytics.fct_orders · 18 columns · 2.1M rows",
    {
      kind: "schema",
      table: "analytics.fct_orders",
      description: "One row per fulfilled order with net revenue after refunds.",
      owner: "data-platform",
      row_count: 2_143_882,
      engine: "postgres",
      columns: FCT_ORDERS_COLUMNS.map((column) => ({
        ...column,
        primary_key: column.primary_key ?? false,
      })),
      columns_truncated: false,
      foreign_keys: [
        { column: "customer_id", references: "analytics.dim_customers.customer_id" },
        { column: "region_id", references: "analytics.dim_regions.region_id" },
      ],
      referenced_by: [
        { table: "analytics.rpt_daily_revenue", column: "order_id", references_column: "order_id" },
      ],
      sample_values: {
        order_quarter: ["2025-Q1", "2025-Q2", "2025-Q3"],
        tier: ["enterprise", "mid-market", "smb"],
        currency: ["USD", "EUR", "GBP"],
      },
    },
    `# analytics.fct_orders (2,143,882 rows)\n${text}`,
  );
}

// --- t3: validate_sql failure → validation ----------------------------------

export const FIXTURE_VALIDATION_ERROR =
  'column "region_name" does not exist on analytics.fct_orders — regions live on dim_regions';

export function fixtureValidationFailureCompletion(toolCallId: string) {
  const resultText = `INVALID ✗\n${FIXTURE_VALIDATION_ERROR}\nSuggested fix: join analytics.dim_regions on region_id and select r.region`;
  return {
    ...completed(
      toolCallId,
      "mcp__signalpilot__validate_sql",
      FIXTURE_VALIDATION_ERROR,
      {
        kind: "validation",
        valid: false,
        message: FIXTURE_VALIDATION_ERROR,
        suggested_fix: "join analytics.dim_regions r on r.region_id = o.region_id and select r.region",
        checks: ["syntax", "column references"],
      },
      resultText,
    ),
    error: true,
  };
}

// --- t4: query_database → table --------------------------------------------

export function fixtureTableCompletion(toolCallId: string) {
  const rows = Array.from({ length: 50 }, (_, index) => fixtureQueryRow(index));
  const header = FIXTURE_QUERY_COLUMNS.map((column) => column.name).join(" | ");
  const body = rows
    .slice(0, 5)
    .map((row) => row.map((value) => (value === null ? "NULL" : String(value))).join(" | "))
    .join("\n");
  return completed(
    toolCallId,
    "mcp__signalpilot__query_database",
    "Preview 50 of 1,204 rows · 312 ms",
    {
      kind: "table",
      columns: FIXTURE_QUERY_COLUMNS,
      rows,
      preview_row_count: 50,
      row_count: FIXTURE_QUERY_ROW_COUNT,
      query_row_count: FIXTURE_QUERY_ROW_COUNT,
      preview_truncated: true,
      columns_truncated: false,
      result_id: FIXTURE_QUERY_RESULT_ID,
      execution_id: "exec-fixture-1",
      execution_ms: 312,
      completeness: "complete",
      truncation_reason: null,
      pii_redacted_columns: ["email"],
      source: "structured",
    },
    `${header}\n${body}\n…\n[1204 rows, 312ms, result res-31, completeness: complete]\n[PII REDACTED] email`,
  );
}

// --- t7: Bash → terminal ---------------------------------------------------

export function fixtureTerminalCompletion(toolCallId: string) {
  const stdout = `[
  {"region": "APAC", "revenue_q3": 2118800, "revenue_q2": 1611200, "growth_pct": 31.5},
  {"region": "EMEA", "revenue_q3": 4812400, "revenue_q2": 4101900, "growth_pct": 17.3},
  {"region": "AMER", "revenue_q3": 9204100, "revenue_q2": 8930600, "growth_pct": 3.1}
]
check: 3 regions, growth sums to 51.9`;
  return completed(
    toolCallId,
    "Bash",
    "python analysis/q3_growth.py --check · exit 0",
    {
      kind: "terminal",
      command: "python analysis/q3_growth.py --check",
      exit_code: 0,
      stdout,
      stderr: "",
      stdout_truncated: false,
      stderr_truncated: false,
    },
    stdout,
  );
}

// --- t13: list_tables → table_list -----------------------------------------

const SCHEMA_TABLES: Record<string, string[]> = {
  analytics: [
    "fct_orders", "fct_order_items", "fct_refunds", "fct_sessions", "fct_subscriptions",
    "dim_customers", "dim_regions", "dim_products", "dim_dates", "dim_channels",
    "rpt_daily_revenue", "rpt_region_rollup", "rpt_cohort_retention", "rpt_tier_mix",
    "agg_monthly_revenue", "agg_customer_ltv",
  ],
  staging: [
    "stg_shopify__orders", "stg_shopify__customers", "stg_shopify__refunds", "stg_shopify__products",
    "stg_stripe__charges", "stg_stripe__invoices", "stg_stripe__subscriptions", "stg_stripe__customers",
    "stg_hubspot__contacts", "stg_hubspot__deals", "stg_hubspot__companies",
    "stg_segment__pages", "stg_segment__tracks", "stg_segment__identifies",
    "stg_exchange_rates", "stg_regions", "stg_calendar",
  ],
  raw: [
    "shopify_orders", "shopify_customers", "shopify_refunds", "shopify_products",
    "stripe_charges", "stripe_invoices", "stripe_subscriptions", "stripe_customers",
    "hubspot_contacts", "hubspot_deals", "hubspot_companies",
    "segment_pages", "segment_tracks", "exchange_rates",
  ],
};

function tableColumns(name: string) {
  const key = name.replace(/^(fct_|dim_|rpt_|agg_|stg_[a-z]+__|shopify_|stripe_|hubspot_|segment_)/, "");
  const singular = key.endsWith("s") ? key.slice(0, -1) : key;
  const columns: { name: string; primary_key: boolean; references?: string }[] = [
    { name: `${singular}_id`, primary_key: true },
  ];
  if (name.startsWith("fct_") || name.startsWith("rpt_")) {
    columns.push(
      { name: "customer_id", primary_key: false, references: "dim_customers.customer_id" },
      { name: "region_id", primary_key: false, references: "dim_regions.region_id" },
      { name: "order_date", primary_key: false },
      { name: "net_revenue", primary_key: false },
    );
  } else {
    columns.push({ name: "name", primary_key: false }, { name: "updated_at", primary_key: false });
  }
  return columns;
}

export function fixtureTableListCompletion(toolCallId: string) {
  const entries = Object.entries(SCHEMA_TABLES).flatMap(([schema, tables]) =>
    tables.map((table, index) => {
      const rowCount = Math.round(1_000 + noise(index, schema.length) * 2_400_000);
      return {
        name: `${schema}.${table}`,
        row_count: rowCount,
        row_count_label: rowCount >= 1_000_000 ? `${(rowCount / 1e6).toFixed(1)}M` : `${Math.round(rowCount / 1e3)}K`,
        columns: tableColumns(table),
        columns_truncated: false,
      };
    }),
  );
  const resultText = entries
    .map((entry) => `${entry.name} (${entry.row_count_label} rows): ${entry.columns.map((c) => (c.primary_key ? `*${c.name}` : c.name)).join(", ")}`)
    .join("\n");
  return completed(
    toolCallId,
    "mcp__signalpilot__list_tables",
    "Discovered 47 tables · 3 schemas",
    {
      kind: "table_list",
      connection: "warehouse_prod",
      database: "analytics_db",
      db_type: "postgres",
      total: entries.length,
      entries,
      entries_truncated: false,
      databases: Object.entries(SCHEMA_TABLES).map(([schema, tables]) => ({
        name: schema,
        table_count: tables.length,
      })),
    },
    resultText,
  );
}

// --- t14: explore_columns → column_profile ---------------------------------

export function fixtureColumnProfileCompletion(toolCallId: string) {
  const columns = [
    {
      name: "region_id", type: "integer", primary_key: false, nullable: false,
      distinct_count: 3, uniqueness: 0.0000014, min: "1", max: "3", null_count: 0, null_pct: 0,
      top_values: [{ value: "1", count: 1_221_408 }, { value: "2", count: 638_770 }, { value: "3", count: 283_704 }],
    },
    {
      name: "net_revenue", type: "numeric(18,2)", nullable: false,
      distinct_count: 418_211, uniqueness: 0.195, min: "0.00", max: "184,220.00", avg: "7,512.40",
      null_count: 0, null_pct: 0,
      top_values: [{ value: "49.00", count: 41_203 }, { value: "99.00", count: 38_115 }, { value: "199.00", count: 22_904 }],
    },
    {
      name: "tier", type: "varchar", nullable: true,
      distinct_count: 4, uniqueness: 0.0000019, null_count: 61_402, null_pct: 2.9,
      sample_values: ["enterprise", "mid-market", "smb", "marketplace"],
      top_values: [
        { value: "smb", count: 1_004_331 }, { value: "mid-market", count: 612_004 },
        { value: "enterprise", count: 341_882 }, { value: "marketplace", count: 124_263 },
      ],
    },
    {
      name: "order_quarter", type: "varchar", nullable: false,
      distinct_count: 7, uniqueness: 0.0000033, min: "2024-Q1", max: "2025-Q3", null_count: 0, null_pct: 0,
      top_values: [{ value: "2025-Q3", count: 389_220 }, { value: "2025-Q2", count: 352_118 }, { value: "2025-Q1", count: 318_004 }],
    },
  ];
  return completed(
    toolCallId,
    "mcp__signalpilot__explore_columns",
    "Profiled 4 columns of analytics.fct_orders",
    {
      kind: "column_profile",
      table: "analytics.fct_orders",
      row_count: 2_143_882,
      columns,
      columns_truncated: false,
    },
    columns.map((column) => `${column.name} (${column.type}): distinct=${column.distinct_count} nulls=${column.null_pct}%`).join("\n"),
  );
}

// --- t15: dbt_execute → dbt_run --------------------------------------------

export const FIXTURE_DBT_LOG = `12:41:03  Running with dbt=1.9.1
12:41:04  Found 36 models, 58 data tests, 3 sources
12:41:05  1 of 13 START sql view model analytics.stg_regions ......................... [RUN]
12:41:05  1 of 13 OK created sql view model analytics.stg_regions .................... [OK in 0.31s]
12:41:06  7 of 13 START sql table model analytics.fct_orders ......................... [RUN]
12:41:09  7 of 13 OK created sql table model analytics.fct_orders .................... [SELECT 2143882 in 3.12s]
12:41:10  11 of 13 START sql table model analytics.rpt_region_rollup ................. [RUN]
12:41:11  11 of 13 ERROR creating sql table model analytics.rpt_region_rollup ........ [ERROR in 0.84s]
12:41:12  13 of 13 OK created sql view model analytics.rpt_tier_mix .................. [OK in 0.22s]
12:41:12  Finished running 9 view models, 4 table models in 0 hours 0 minutes and 8.40 seconds (8.40s).
12:41:12  Completed with 1 error and 0 warnings:
12:41:12    Database Error in model rpt_region_rollup (models/marts/rpt_region_rollup.sql)
12:41:12      column "region_name" does not exist
12:41:12  Done. PASS=12 WARN=0 ERROR=1 SKIP=0 TOTAL=13`;

export function fixtureDbtRunCompletion(toolCallId: string) {
  return completed(
    toolCallId,
    "mcp__signalpilot__dbt_execute",
    "dbt run · 12 ✓ 1 ✗ · 8.4 s",
    {
      kind: "dbt_run",
      command: "dbt run --select marts.revenue+",
      target_schema: "analytics",
      sync: "pushed",
      exit_code: 1,
      statuses: { success: 12, error: 1 },
      total: 13,
      failures: [
        {
          node: "model.analytics.rpt_region_rollup",
          message: 'column "region_name" does not exist',
        },
      ],
      elapsed_s: 8.4,
      log: FIXTURE_DBT_LOG,
      log_truncated: false,
    },
    FIXTURE_DBT_LOG,
  );
}

// --- t16: search_knowledge → knowledge -------------------------------------

export function fixtureKnowledgeCompletion(toolCallId: string) {
  const docs = [
    {
      id: "kb-114", scope: "org", category: "definitions", title: "Net revenue",
      snippet: "Gross revenue minus discounts and refunds issued before quarter close. Refunds after close land in the following quarter.",
    },
    {
      id: "kb-207", scope: "project", category: "conventions", title: "Region dimension join",
      snippet: "Always join analytics.dim_regions on region_id; fct_orders carries no region name column.",
    },
    {
      id: "kb-311", scope: "connection", category: "caveats", title: "APAC marketplace launches",
      snippet: "Two marketplace launches in 2025-Q3 inflate APAC growth from a small Q2 base.",
    },
  ];
  return completed(
    toolCallId,
    "mcp__signalpilot__search_knowledge",
    "3 knowledge docs",
    {
      kind: "knowledge",
      mode: "search",
      query: "net revenue region definition",
      docs,
      total: 3,
      truncated: false,
    },
    docs.map((doc) => `id=${doc.id} scope=${doc.scope} category=${doc.category} title=${doc.title}\nsnippet: ${doc.snippet}`).join("\n\n"),
  );
}

// --- t17: external connector (HubSpot) → json ------------------------------

export function fixtureConnectorJsonCompletion(toolCallId: string) {
  const value = {
    total: 2,
    results: [
      {
        id: "51201",
        properties: { firstname: "Priya", lastname: "Natarajan", company: "Northwind Traders", lifecyclestage: "customer", region: "APAC" },
      },
      {
        id: "51244",
        properties: { firstname: "Marcus", lastname: "Feld", company: "Contoso GmbH", lifecyclestage: "customer", region: "EMEA" },
      },
    ],
    paging: null,
  };
  const resultText = JSON.stringify(value, null, 2);
  return completed(
    toolCallId,
    "mcp__hubspot__search_contacts",
    "2 contacts",
    { kind: "json", value },
    resultText,
  );
}

// --- follow-up tool chain (21.2–24.0 s) ------------------------------------

function toolPair(
  runId: string,
  startAt: number,
  endAt: number,
  tool: string,
  toolCallId: string,
  input: Record<string, unknown>,
  completion: Record<string, unknown>,
): FixtureEvent[] {
  return [
    {
      at: startAt,
      run_id: runId,
      sequence: 0,
      type: "tool_started",
      payload: { tool, tool_call_id: toolCallId, input },
    },
    {
      at: endAt,
      run_id: runId,
      sequence: 0,
      type: "tool_completed",
      payload: completion,
    },
  ];
}

/**
 * The follow-up tool chain replayed after the answer (21.2–24.0 s): one
 * tool_started/tool_completed pair per structured result kind the answer
 * did not already exercise, plus one external connector call.
 */
export function followUpToolEvents(runId: string): FixtureEvent[] {
  return [
    ...toolPair(runId, 21_200, 21_650, "mcp__signalpilot__list_tables", "t13",
      { connection: "warehouse_prod", schema_name: "analytics" },
      fixtureTableListCompletion("t13")),
    ...toolPair(runId, 21_800, 22_300, "mcp__signalpilot__explore_columns", "t14",
      { schema_name: "analytics", table_name: "fct_orders", columns: ["region_id", "net_revenue", "tier", "order_quarter"] },
      fixtureColumnProfileCompletion("t14")),
    ...toolPair(runId, 22_400, 23_300, "mcp__signalpilot__dbt_execute", "t15",
      { command: "run", select: "marts.revenue+" },
      fixtureDbtRunCompletion("t15")),
    ...toolPair(runId, 23_400, 23_650, "mcp__signalpilot__search_knowledge", "t16",
      { query: "net revenue region definition" },
      fixtureKnowledgeCompletion("t16")),
    ...toolPair(runId, 23_700, 23_950, "mcp__hubspot__search_contacts", "t17",
      { query: "Northwind OR Contoso", properties: ["firstname", "lastname", "company", "lifecyclestage"] },
      fixtureConnectorJsonCompletion("t17")),
  ];
}
