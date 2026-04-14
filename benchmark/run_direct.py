"""Entry point with suite routing for Spider2 benchmark runners.

Kept so that existing invocations still work:
    python -m benchmark.run_direct chinook001
    python benchmark/run_direct.py chinook001
    python -m benchmark.run_direct --suite spider2-snowflake sf_tpch001
    python -m benchmark.run_direct --suite spider2-lite lite_sqlite001
"""

from __future__ import annotations

import sys


def main() -> None:
    """Route to the appropriate suite runner based on --suite flag."""
    suite_value: str | None = None
    args = list(sys.argv[1:])

    # Peek at args for --suite flag and consume it
    for i, arg in enumerate(args):
        if arg == "--suite" and i + 1 < len(args):
            suite_value = args[i + 1]
            del args[i : i + 2]
            sys.argv = [sys.argv[0]] + args
            break
        if arg.startswith("--suite="):
            suite_value = arg.split("=", 1)[1]
            del args[i]
            sys.argv = [sys.argv[0]] + args
            break

    if suite_value in ("spider2-snowflake", "spider2-lite"):
        from benchmark.core.suite import BenchmarkSuite
        from benchmark.runners.sql_runner import main as sql_main

        if suite_value == "spider2-snowflake":
            sql_main(BenchmarkSuite.SNOWFLAKE)
        else:
            sql_main(BenchmarkSuite.LITE)
    else:
        # Default: DBT suite (also handles --suite spider2-dbt or no --suite)
        from benchmark.runners.direct import main as dbt_main

        dbt_main()


if __name__ == "__main__":
    main()
