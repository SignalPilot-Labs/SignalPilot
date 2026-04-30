"""BenchmarkSuite enum and per-suite configuration factory."""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from pathlib import Path

from .paths import (
    BENCHMARK_DIR,
    EVAL_JSONL,
    GOLD_DIR,
    SPIDER2_DBT_DIR,
    SPIDER2_LITE_DIR,
    SPIDER2_SNOWFLAKE_DIR,
    SQL_WORK_DIR,
    TASK_JSONL,
    WORK_DIR,
)

TEST_TASKS_DIR = BENCHMARK_DIR / "tests" / "tasks"


class BenchmarkSuite(str, Enum):
    DBT = "spider2-dbt"
    SNOWFLAKE = "spider2-snowflake"
    LITE = "spider2-lite"


class DBBackend(str, Enum):
    DUCKDB = "duckdb"
    SNOWFLAKE = "snowflake"
    BIGQUERY = "bigquery"
    SQLITE = "sqlite"


@dataclass
class SuiteConfig:
    suite: BenchmarkSuite
    data_dir: Path
    task_jsonl: Path
    eval_jsonl: Path
    gold_dir: Path
    work_dir: Path
    skills: list[str]


def get_suite_config(suite: BenchmarkSuite) -> SuiteConfig:
    """Factory: build SuiteConfig for the given suite from env vars / path conventions."""
    if suite == BenchmarkSuite.DBT:
        return SuiteConfig(
            suite=suite,
            data_dir=SPIDER2_DBT_DIR,
            task_jsonl=TASK_JSONL,
            eval_jsonl=EVAL_JSONL,
            gold_dir=GOLD_DIR,
            work_dir=WORK_DIR,
            skills=["dbt-workflow", "dbt-debugging", "dbt-date-spines", "duckdb-sql"],
        )

    if suite == BenchmarkSuite.SNOWFLAKE:
        data_dir = SPIDER2_SNOWFLAKE_DIR
        return SuiteConfig(
            suite=suite,
            data_dir=data_dir,
            task_jsonl=data_dir / "spider2-snow.jsonl",
            eval_jsonl=data_dir / "evaluation_suite" / "gold" / "spider2snow_eval.jsonl",
            gold_dir=data_dir / "evaluation_suite" / "gold",
            work_dir=SQL_WORK_DIR / "snowflake",
            skills=["sql-workflow", "snowflake-sql"],
        )

    if suite == BenchmarkSuite.LITE:
        data_dir = SPIDER2_LITE_DIR
        return SuiteConfig(
            suite=suite,
            data_dir=data_dir,
            task_jsonl=data_dir / "spider2-lite.jsonl",
            eval_jsonl=data_dir / "evaluation_suite" / "gold" / "spider2lite_eval.jsonl",
            gold_dir=data_dir / "evaluation_suite" / "gold",
            work_dir=SQL_WORK_DIR / "lite",
            skills=["sql-workflow", "snowflake-sql", "bigquery-sql", "sqlite-sql"],
        )

    raise ValueError(f"Unknown suite: {suite}")


def get_test_suite_config(suite: BenchmarkSuite) -> SuiteConfig:
    """Like get_suite_config but uses synthetic test data from tests/tasks/."""
    if suite == BenchmarkSuite.DBT:
        return SuiteConfig(
            suite=suite,
            data_dir=TEST_TASKS_DIR / "dbt_projects",
            task_jsonl=TEST_TASKS_DIR / "spider2-dbt.jsonl",
            eval_jsonl=TEST_TASKS_DIR / "eval" / "dbt" / "spider2_eval.jsonl",
            gold_dir=TEST_TASKS_DIR / "gold" / "dbt",
            work_dir=TEST_TASKS_DIR / "_workdir" / "dbt",
            skills=["dbt-workflow", "dbt-debugging", "dbt-date-spines", "duckdb-sql"],
        )

    if suite == BenchmarkSuite.SNOWFLAKE:
        return SuiteConfig(
            suite=suite,
            data_dir=TEST_TASKS_DIR,
            task_jsonl=TEST_TASKS_DIR / "spider2-snowflake.jsonl",
            eval_jsonl=TEST_TASKS_DIR / "eval" / "snowflake" / "spider2snow_eval.jsonl",
            gold_dir=TEST_TASKS_DIR / "gold" / "snowflake",
            work_dir=TEST_TASKS_DIR / "_workdir" / "snowflake",
            skills=["sql-workflow", "snowflake-sql"],
        )

    if suite == BenchmarkSuite.LITE:
        return SuiteConfig(
            suite=suite,
            data_dir=TEST_TASKS_DIR,
            task_jsonl=TEST_TASKS_DIR / "spider2-lite.jsonl",
            eval_jsonl=TEST_TASKS_DIR / "eval" / "lite" / "spider2lite_eval.jsonl",
            gold_dir=TEST_TASKS_DIR / "gold" / "lite",
            work_dir=TEST_TASKS_DIR / "_workdir" / "lite",
            skills=["sql-workflow", "snowflake-sql", "bigquery-sql", "sqlite-sql"],
        )

    raise ValueError(f"Unknown suite for test config: {suite}")
