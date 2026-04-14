"""Entry point router for all Spider2 benchmark suites.

Routes to the correct runner based on --suite flag.

Usage:
    python -m benchmark.run_direct chinook001
    python -m benchmark.run_direct chinook001 --suite spider2-dbt
    python -m benchmark.run_direct sf_tpch001 --suite spider2-snowflake
    python -m benchmark.run_direct lite_sqlite001 --suite spider2-lite
"""

from __future__ import annotations

import argparse
import io
import sys

if sys.stdout.encoding != "utf-8":
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
    sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding="utf-8", errors="replace")


def main() -> None:
    # Pre-parse only --suite so we can route before delegating full arg parsing
    # to the target runner. Use parse_known_args to avoid consuming runner-specific flags.
    pre_parser = argparse.ArgumentParser(add_help=False)
    pre_parser.add_argument(
        "--suite",
        default="spider2-dbt",
        choices=["spider2-dbt", "spider2-snowflake", "spider2-lite"],
    )
    pre_args, remaining = pre_parser.parse_known_args()
    sys.argv = [sys.argv[0]] + remaining  # strip --suite before delegating

    suite_name: str = pre_args.suite

    if suite_name == "spider2-dbt":
        from benchmark.runners.direct import main as dbt_main
        dbt_main()

    elif suite_name == "spider2-snowflake":
        from benchmark.core.suite import BenchmarkSuite
        from benchmark.runners.sql_runner import main as sql_main
        sql_main(BenchmarkSuite.SNOWFLAKE)

    elif suite_name == "spider2-lite":
        from benchmark.core.suite import BenchmarkSuite
        from benchmark.runners.sql_runner import main as sql_main
        sql_main(BenchmarkSuite.LITE)

    else:
        print(f"Unknown suite: {suite_name}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
