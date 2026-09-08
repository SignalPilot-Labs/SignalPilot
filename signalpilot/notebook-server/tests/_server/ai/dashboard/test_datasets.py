"""Dataset loading: CSV coercion, JSON, and path safety."""

from __future__ import annotations

from typing import TYPE_CHECKING

import pytest

from signalpilot._server.ai.dashboard.datasets import (
    coerce_cell,
    load_dataset,
    load_datasets,
    parse_dataset_text,
    resolve_scratch_path,
)

if TYPE_CHECKING:
    from pathlib import Path


def test_coerce_cell_numeric_and_empty():
    assert coerce_cell("12") == 12
    assert isinstance(coerce_cell("12"), int)
    assert coerce_cell(" 3.5 ") == 3.5
    assert coerce_cell("-1e3") == -1000.0
    assert coerce_cell("") is None
    assert coerce_cell("   ") is None
    assert coerce_cell("abc") == "abc"
    assert coerce_cell("12abc") == "12abc"
    assert coerce_cell("nan") == "nan"
    assert coerce_cell("2025-01-01") == "2025-01-01"


def test_parse_csv_and_tsv_with_quotes():
    csv_text = 'month,region,revenue\n2025-01-01,"East, US",10.5\n2025-02-01,West,\n\n'
    rows = parse_dataset_text(csv_text, "artifacts/m.csv")
    assert rows == [
        {"month": "2025-01-01", "region": "East, US", "revenue": 10.5},
        {"month": "2025-02-01", "region": "West", "revenue": None},
    ]
    tsv_text = "a\tb\n1\tx\n"
    assert parse_dataset_text(tsv_text, "artifacts/m.tsv") == [
        {"a": 1, "b": "x"}
    ]
    assert parse_dataset_text("", "artifacts/e.csv") == []


def test_parse_json_array_of_objects():
    rows = parse_dataset_text(
        '[{"a": 1, "b": "x"}, {"a": null}]', "artifacts/m.json"
    )
    assert rows == [{"a": 1, "b": "x"}, {"a": None}]
    with pytest.raises(ValueError, match="array of objects"):
        parse_dataset_text('{"a": 1}', "artifacts/m.json")
    with pytest.raises(ValueError, match="item 1 is not an object"):
        parse_dataset_text("[{}, 3]", "artifacts/m.json")
    with pytest.raises(ValueError, match="Unsupported"):
        parse_dataset_text("a,b", "artifacts/m.parquet")


def test_resolve_scratch_path_rejects_escapes(tmp_path: Path):
    (tmp_path / "artifacts").mkdir()
    ok = resolve_scratch_path(tmp_path, "artifacts/sub/x.csv")
    assert ok == (tmp_path / "artifacts" / "sub" / "x.csv").resolve()
    for bad in (
        "x.csv",
        "artifacts",
        "artifacts/",
        "/artifacts/x.csv",
        "artifacts/../secret.csv",
        "artifacts/./x.csv",
        "../artifacts/x.csv",
        "notebooks/x.csv",
    ):
        with pytest.raises(ValueError, match="Path"):
            resolve_scratch_path(tmp_path, bad)


def test_load_dataset_file_and_rows(tmp_path: Path):
    (tmp_path / "artifacts").mkdir()
    (tmp_path / "artifacts" / "m.csv").write_text(
        "month,revenue\n2025-01-01,10\n", encoding="utf-8"
    )
    loaded = load_dataset(tmp_path, {"file": "artifacts/m.csv"})
    assert loaded.error is None
    assert loaded.resolved_file == "artifacts/m.csv"
    assert loaded.rows == [{"month": "2025-01-01", "revenue": 10}]

    inline = load_dataset(tmp_path, {"rows": [{"a": 1}, "junk"]})
    assert inline.rows == [{"a": 1}]
    assert inline.resolved_file is None

    missing = load_dataset(tmp_path, {"file": "artifacts/none.csv"})
    assert missing.error is not None
    assert "artifacts/none.csv" in missing.error

    escaped = load_dataset(tmp_path, {"file": "artifacts/../m.csv"})
    assert escaped.error is not None

    (tmp_path / "artifacts" / "bad.json").write_text("{", encoding="utf-8")
    broken = load_dataset(tmp_path, {"file": "artifacts/bad.json"})
    assert broken.error is not None
    assert "artifacts/bad.json" in broken.error

    assert load_dataset(tmp_path, "nope").error is not None
    assert load_dataset(tmp_path, {}).error is not None


def test_load_datasets_selects_names(tmp_path: Path):
    spec = {
        "datasets": {
            "a": {"rows": [{"x": 1}]},
            "b": {"rows": [{"x": 2}]},
        }
    }
    assert set(load_datasets(tmp_path, spec)) == {"a", "b"}
    assert set(load_datasets(tmp_path, spec, {"b"})) == {"b"}
