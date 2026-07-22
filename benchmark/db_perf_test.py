"""Automated cross-DB performance test for SignalPilot's heavy MCP tools.

Runs the heavy / schema-pull MCP tools against each registered connection over
the real MCP protocol (agent path), times cold + warm, and prints a comparison
report. Usage: MCPKEY=<key> python db_perf_test.py
"""
import asyncio
import os
import time

from mcp import ClientSession
from mcp.client.streamable_http import streamablehttp_client

MCP_URL = os.environ.get("MCP_URL", "http://localhost:3300/mcp")
KEY = os.environ["MCPKEY"]

# (display label, real connection name)
CONNS = [
    ("Postgres (local)", "perf_nala_pg"),
    ("Redshift Serverless", "perf_redshift"),
]
TABLE = "raw_core_transfers.transfers"
AGG_SQL = (
    'SELECT "status", count(*) AS c, sum("send_amount") AS s '
    'FROM "raw_core_transfers"."transfers" GROUP BY "status" ORDER BY c DESC'
)


def tool_calls(conn: str):
    # (label, tool_name, args) — heavy MCP calls + schema pulls
    return [
        ("schema_overview", "schema_overview", {"connection_name": conn}),
        ("list_tables", "list_tables", {"connection_name": conn}),
        ("schema_statistics", "schema_statistics", {"connection_name": conn}),
        ("schema_ddl (full pull)", "schema_ddl", {"connection_name": conn, "max_tables": 100}),
        ("schema_link", "schema_link", {"connection_name": conn, "question": "total send_amount by corridor and status"}),
        ("get_relationships", "get_relationships", {"connection_name": conn}),
        ("describe_table", "describe_table", {"connection_name": conn, "table_name": TABLE}),
        ("explore_table", "explore_table", {"connection_name": conn, "table_name": TABLE}),
        ("analyze_grain", "analyze_grain", {"connection_name": conn, "table_name": TABLE, "candidate_keys": "transfer_id"}),
        ("analyze_project_db", "analyze_project_db", {"connection_name": conn}),
        ("query_database (agg)", "query_database", {"connection_name": conn, "sql": AGG_SQL, "row_limit": 50}),
    ]


async def run_conn(session, conn: str):
    """Return {label: {cold_ms, warm_ms, ok}} for one connection."""
    out = {}
    for label, tool, args in tool_calls(conn):
        timings = []
        ok = True
        for _ in range(2):  # cold, then warm
            t = time.monotonic()
            try:
                res = await session.call_tool(tool, args)
                txt = res.content[0].text if res.content else ""
                if txt.strip().lower().startswith("error") or "error:" in txt[:40].lower():
                    ok = False
            except Exception as e:
                ok = False
                txt = f"EXC {e}"
            timings.append((time.monotonic() - t) * 1000)
        out[label] = {"cold_ms": timings[0], "warm_ms": timings[1], "ok": ok}
    return out


async def main():
    results = {}
    async with streamablehttp_client(MCP_URL, headers={"X-API-Key": KEY}) as (r, w, _):
        async with ClientSession(r, w) as session:
            await session.initialize()
            for disp, conn in CONNS:
                print(f"... benchmarking {disp} ({conn})", flush=True)
                try:
                    results[disp] = await run_conn(session, conn)
                except Exception as e:
                    print(f"    connection failed: {e}", flush=True)
                    results[disp] = {}

    labels = [c[0] for c in tool_calls("x")]
    dbs = [d for d, _ in CONNS]
    w0 = 24
    print("\n" + "=" * 90)
    print("  HEAVY MCP CALL PERFORMANCE — warm ms (cold ms) — ✗ = error")
    print("=" * 90)
    header = "TOOL".ljust(w0) + "".join(d[:16].ljust(18) for d in dbs)
    print(header)
    print("-" * len(header))
    for lab in labels:
        row = lab.ljust(w0)
        for d in dbs:
            cell = results.get(d, {}).get(lab)
            if not cell:
                row += "—".ljust(18)
            else:
                mark = "" if cell["ok"] else " ✗"
                row += f"{cell['warm_ms']:.0f} ({cell['cold_ms']:.0f}){mark}".ljust(18)
        print(row)
    print("-" * len(header))
    # totals (warm)
    trow = "TOTAL warm (s)".ljust(w0)
    for d in dbs:
        tot = sum(v["warm_ms"] for v in results.get(d, {}).values()) / 1000
        trow += f"{tot:.2f}".ljust(18)
    print(trow)
    print("=" * 90)


asyncio.run(main())
