"""Verify manifest v2 parsing in gateway/evals/manifest.py.

The manifest supplies SQL identifiers and container scripts. The parser rejects
path escapes and invalid task-class grading combinations.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from gateway.evals.manifest import (
    DEFAULT_TOLERANCE,
    ManifestError,
    load_eval_set,
    read_claude_md,
)


def _write_repo(tmp_path: Path, manifest: dict, files: dict[str, str] | None = None) -> Path:
    repo = tmp_path / "repo"
    repo.mkdir(exist_ok=True)
    repo.joinpath("eval.json").write_text(json.dumps(manifest), encoding="utf-8")
    for rel, text in (files or {}).items():
        p = repo / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(text, encoding="utf-8")
    return repo


def _task(**overrides) -> dict:
    base = {"id": "q1", "prompt_text": "how many orders?", "gt": "42"}
    base.update(overrides)
    return base


class TestHappyPath:
    def test_full_manifest_parses(self, tmp_path: Path) -> None:
        repo = _write_repo(
            tmp_path,
            {
                "name": "northwind",
                "description": "desc",
                "project_repo": "https://github.com/acme/dbt.git",
                "build_fingerprint": "fp-abc",
                "setup": {"timeout_seconds": 900},
                "defaults": {"tolerance": 0.05},
                "tasks": [
                    _task(id="read-1", title="Read", why="because", covers=["fct_orders"]),
                    {
                        "id": "write-1",
                        "class": "write",
                        "prompt": "prompts/write-1.txt",
                        "setup": "scripts/break.sh",
                        "teardown": "scripts/fix.sh",
                        "builds": ["marts.fct_orders"],
                        "grade": {
                            "kind": "model_rebuilt",
                            "model": "marts.fct_orders",
                            "expect": {"row_count": 100, "grain": ["order_id"]},
                        },
                        "capture": {"mode": "fingerprint+sample", "sample_rows": 50},
                    },
                ],
            },
            files={
                "prompts/write-1.txt": "rebuild the mart",
                "scripts/break.sh": "echo break",
                "scripts/fix.sh": "echo fix",
                "docs/read-1.md": "gold doc",
            },
        )
        es = load_eval_set(repo)
        assert es.name == "northwind"
        assert es.project_repo == "https://github.com/acme/dbt.git"
        assert es.build_fingerprint == "fp-abc"
        assert es.setup["timeout_seconds"] == 900
        assert [t.id for t in es.tasks] == ["read-1", "write-1"]

        read = es.tasks[0]
        assert read.task_class == "read"
        assert read.prompt == "how many orders?"
        assert read.doc == "gold doc"
        assert read.checks == [{"name": "answer", "value": 42.0, "tolerance": 0.05}]
        assert read.grade == {"kind": "checks"}
        assert read.covers == ["fct_orders"]
        assert read.capture is None

        write = es.tasks[1]
        assert write.task_class == "write"
        assert write.prompt == "rebuild the mart"
        assert write.setup == "scripts/break.sh"
        assert write.teardown == "scripts/fix.sh"
        assert write.grade["kind"] == "model_rebuilt"
        assert write.grade["model"] == "marts.fct_orders"
        assert write.capture == {
            "tables": ["marts.fct_orders"],
            "mode": "fingerprint+sample",
            "sample_rows": 50,
        }

    def test_defaults(self, tmp_path: Path) -> None:
        repo = _write_repo(tmp_path, {"tasks": [_task()]})
        es = load_eval_set(repo)
        t = es.tasks[0]
        assert es.name == "repo"  # falls back to the directory name
        assert t.task_class == "read"
        assert t.kind == "query"
        assert t.title == "q1"
        assert t.checks[0]["tolerance"] == DEFAULT_TOLERANCE
        assert t.grade == {"kind": "checks"}
        assert t.setup == "" and t.teardown == ""
        assert t.builds == [] and t.covers == []

    def test_manifest_cannot_request_a_network(self, tmp_path: Path) -> None:
        repo = _write_repo(
            tmp_path,
            {"setup": {"network": "signalpilot_default"}, "tasks": [_task()]},
        )
        with pytest.raises(ManifestError, match="unsupported setup keys: network"):
            load_eval_set(repo)

    def test_manifest_cannot_choose_an_image(self, tmp_path: Path) -> None:
        repo = _write_repo(
            tmp_path,
            {"setup": {"image": "attacker/image:latest"}, "tasks": [_task()]},
        )
        with pytest.raises(ManifestError, match="unsupported setup keys: image"):
            load_eval_set(repo)

    def test_gt_to_checks_fallback_strips_currency(self, tmp_path: Path) -> None:
        repo = _write_repo(tmp_path, {"tasks": [_task(gt="$1,234,567")]})
        assert load_eval_set(repo).tasks[0].checks[0]["value"] == 1234567.0

    def test_non_numeric_gt_yields_no_checks(self, tmp_path: Path) -> None:
        repo = _write_repo(tmp_path, {"tasks": [_task(gt="the fan-out is the bug")]})
        assert load_eval_set(repo).tasks[0].checks == []

    def test_explicit_checks_win_over_gt(self, tmp_path: Path) -> None:
        repo = _write_repo(
            tmp_path,
            {"tasks": [_task(gt="42", checks=[{"name": "n", "value": 7, "tolerance": 0.01}])]},
        )
        assert load_eval_set(repo).tasks[0].checks == [
            {"name": "n", "value": 7.0, "tolerance": 0.01}
        ]

    def test_write_task_with_builds_gets_a_default_fingerprint_capture(self, tmp_path: Path) -> None:
        repo = _write_repo(
            tmp_path,
            {"tasks": [_task(**{"class": "write", "builds": ["marts.fct_x"]})]},
        )
        cap = load_eval_set(repo).tasks[0].capture
        assert cap == {"tables": ["marts.fct_x"], "mode": "fingerprint", "sample_rows": 10_000}

    def test_model_rebuilt_defaults_builds_to_the_graded_model(self, tmp_path: Path) -> None:
        repo = _write_repo(
            tmp_path,
            {
                "tasks": [
                    _task(
                        **{
                            "class": "write",
                            "grade": {"kind": "model_rebuilt", "model": "marts.fct_x"},
                        }
                    )
                ]
            },
        )
        t = load_eval_set(repo).tasks[0]
        assert t.builds == ["marts.fct_x"]

    def test_prompt_file_is_read_when_no_prompt_text(self, tmp_path: Path) -> None:
        repo = _write_repo(
            tmp_path,
            {"tasks": [{"id": "q1", "gt": "1"}]},
            files={"prompts/q1.txt": "from the file"},
        )
        assert load_eval_set(repo).tasks[0].prompt == "from the file"


class TestRefusals:
    def test_no_eval_json(self, tmp_path: Path) -> None:
        (tmp_path / "empty").mkdir()
        with pytest.raises(ManifestError, match="no eval.json"):
            load_eval_set(tmp_path / "empty")

    def test_invalid_json(self, tmp_path: Path) -> None:
        repo = tmp_path / "repo"
        repo.mkdir()
        (repo / "eval.json").write_text("{not json", encoding="utf-8")
        with pytest.raises(ManifestError, match="not valid JSON"):
            load_eval_set(repo)

    def test_missing_tasks(self, tmp_path: Path) -> None:
        repo = _write_repo(tmp_path, {"name": "x"})
        with pytest.raises(ManifestError, match=r"no tasks\[\]"):
            load_eval_set(repo)

    def test_legacy_questions_key_gets_a_migration_hint(self, tmp_path: Path) -> None:
        repo = _write_repo(tmp_path, {"questions": [_task()]})
        with pytest.raises(ManifestError, match="legacy 'questions'"):
            load_eval_set(repo)

    def test_empty_tasks_list(self, tmp_path: Path) -> None:
        repo = _write_repo(tmp_path, {"tasks": []})
        with pytest.raises(ManifestError, match="no tasks"):
            load_eval_set(repo)

    def test_duplicate_task_ids(self, tmp_path: Path) -> None:
        repo = _write_repo(tmp_path, {"tasks": [_task(), _task()]})
        with pytest.raises(ManifestError, match="duplicate task id: q1"):
            load_eval_set(repo)

    def test_task_without_id(self, tmp_path: Path) -> None:
        repo = _write_repo(tmp_path, {"tasks": [{"prompt_text": "x"}]})
        with pytest.raises(ManifestError, match="every task needs an id"):
            load_eval_set(repo)

    def test_prompt_file_missing(self, tmp_path: Path) -> None:
        repo = _write_repo(tmp_path, {"tasks": [{"id": "q1"}]})
        with pytest.raises(ManifestError, match="prompt file missing"):
            load_eval_set(repo)

    def test_prompt_path_escape_is_refused(self, tmp_path: Path) -> None:
        (tmp_path / "outside.txt").write_text("secret", encoding="utf-8")
        repo = _write_repo(
            tmp_path, {"tasks": [{"id": "q1", "prompt": "../outside.txt"}]}
        )
        with pytest.raises(ManifestError, match="escapes the eval repo"):
            load_eval_set(repo)

    def test_setup_script_path_escape_is_refused(self, tmp_path: Path) -> None:
        (tmp_path / "evil.sh").write_text("boom", encoding="utf-8")
        repo = _write_repo(
            tmp_path,
            {"tasks": [_task(**{"class": "write", "setup": "../evil.sh"})]},
        )
        with pytest.raises(ManifestError, match="escapes the eval repo"):
            load_eval_set(repo)

    def test_setup_script_must_exist(self, tmp_path: Path) -> None:
        repo = _write_repo(
            tmp_path,
            {"tasks": [_task(**{"class": "write", "setup": "scripts/nope.sh"})]},
        )
        with pytest.raises(ManifestError, match="setup script not found"):
            load_eval_set(repo)

    def test_setup_on_a_read_task_is_refused(self, tmp_path: Path) -> None:
        """Read tasks share a branch nothing may mutate."""
        repo = _write_repo(
            tmp_path,
            {"tasks": [_task(setup="scripts/x.sh")]},
            files={"scripts/x.sh": "echo"},
        )
        with pytest.raises(ManifestError, match="only valid on write tasks"):
            load_eval_set(repo)

    def test_model_rebuilt_requires_class_write(self, tmp_path: Path) -> None:
        repo = _write_repo(
            tmp_path,
            {"tasks": [_task(grade={"kind": "model_rebuilt", "model": "marts.fct_x"})]},
        )
        with pytest.raises(ManifestError, match="requires class: write"):
            load_eval_set(repo)

    def test_model_rebuilt_needs_a_model(self, tmp_path: Path) -> None:
        repo = _write_repo(
            tmp_path,
            {"tasks": [_task(**{"class": "write", "grade": {"kind": "model_rebuilt"}})]},
        )
        with pytest.raises(ManifestError, match="needs a model"):
            load_eval_set(repo)

    def test_unknown_grade_kind(self, tmp_path: Path) -> None:
        repo = _write_repo(tmp_path, {"tasks": [_task(grade={"kind": "vibes"})]})
        with pytest.raises(ManifestError, match="unknown grade kind"):
            load_eval_set(repo)

    def test_capture_on_a_read_task_is_refused(self, tmp_path: Path) -> None:
        repo = _write_repo(
            tmp_path, {"tasks": [_task(capture={"tables": ["fct_x"]})]}
        )
        with pytest.raises(ManifestError, match="capture is only valid on write tasks"):
            load_eval_set(repo)

    def test_capture_without_tables_or_builds(self, tmp_path: Path) -> None:
        repo = _write_repo(tmp_path, {"tasks": [_task(**{"class": "write", "capture": {}})]})
        with pytest.raises(ManifestError, match="capture needs tables"):
            load_eval_set(repo)

    def test_unknown_capture_mode(self, tmp_path: Path) -> None:
        repo = _write_repo(
            tmp_path,
            {"tasks": [_task(**{"class": "write", "capture": {"tables": ["x"], "mode": "everything"}})]},
        )
        with pytest.raises(ManifestError, match="unknown capture mode"):
            load_eval_set(repo)

    def test_nonpositive_sample_rows(self, tmp_path: Path) -> None:
        repo = _write_repo(
            tmp_path,
            {"tasks": [_task(**{"class": "write", "capture": {"tables": ["x"], "sample_rows": 0}})]},
        )
        with pytest.raises(ManifestError, match="sample_rows must be positive"):
            load_eval_set(repo)

    def test_bad_default_class(self, tmp_path: Path) -> None:
        repo = _write_repo(tmp_path, {"defaults": {"class": "mutate"}, "tasks": [_task()]})
        with pytest.raises(ManifestError, match="defaults.class"):
            load_eval_set(repo)

    def test_bad_task_class(self, tmp_path: Path) -> None:
        repo = _write_repo(tmp_path, {"tasks": [_task(**{"class": "admin"})]})
        with pytest.raises(ManifestError, match="class must be one of"):
            load_eval_set(repo)

    def test_non_numeric_check_value(self, tmp_path: Path) -> None:
        repo = _write_repo(tmp_path, {"tasks": [_task(checks=[{"value": "lots"}])]})
        with pytest.raises(ManifestError, match="non-numeric check"):
            load_eval_set(repo)

    def test_check_without_value(self, tmp_path: Path) -> None:
        repo = _write_repo(tmp_path, {"tasks": [_task(checks=[{"name": "n"}])]})
        with pytest.raises(ManifestError, match="each check needs at least a value"):
            load_eval_set(repo)


class TestClaudeMd:
    def test_reads_either_casing(self, tmp_path: Path) -> None:
        repo = _write_repo(tmp_path, {"tasks": [_task()]}, files={"CLAUDE.md": "# ctx"})
        assert read_claude_md(repo) == "# ctx"

    def test_absent_is_empty(self, tmp_path: Path) -> None:
        repo = _write_repo(tmp_path, {"tasks": [_task()]})
        assert read_claude_md(repo) == ""
