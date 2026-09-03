"""dbt map pipeline: tree-read batching, graph distillation, trigger config."""

from __future__ import annotations

import subprocess
from pathlib import Path

from gateway.dbt_map.runner import classify_failure, distill_graph
from gateway.dbt_map.triggers import _watched_branches
from gateway.workspace_store.github_sync import _is_skipped_path, _read_repo_tree
from gateway.workspace_store.model import dbt_graph_key, dbt_manifest_key, project_prefix


# ── _read_repo_tree (git cat-file --batch path) ──────────────────────────────


def _make_bare_with_content(tmp_path: Path, files: dict[str, str]) -> Path:
    src = tmp_path / "src"
    src.mkdir()
    subprocess.run(["git", "init", "--initial-branch", "main", str(src)], check=True, capture_output=True)
    for rel, text in files.items():
        p = src / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(text, encoding="utf-8")
    idargs = ["-c", "user.email=t@t", "-c", "user.name=t"]
    subprocess.run(["git", *idargs, "-C", str(src), "add", "-A"], check=True, capture_output=True)
    subprocess.run(["git", *idargs, "-C", str(src), "commit", "-m", "c"], check=True, capture_output=True)
    bare = tmp_path / "bare.git"
    subprocess.run(["git", "clone", "--bare", str(src), str(bare)], check=True, capture_output=True)
    return bare


def test_read_repo_tree_batch_reads_all_blobs(tmp_path):
    files = {
        "dbt_project.yml": "name: demo\nprofile: demo\n",
        "models/orders.sql": "select 1",
        "models/staging/stg_orders.sql": "select * from raw",
        "dup_a.txt": "same-bytes",
        "dup_b.txt": "same-bytes",  # duplicate blob sha — batch must dedupe
    }
    bare = _make_bare_with_content(tmp_path, files)
    tree = _read_repo_tree(bare, "refs/heads/main")
    assert {p: c.decode() for p, (c, _m) in tree.items()} == files
    assert all(mode == 0o644 for _c, mode in tree.values())


def test_read_repo_tree_skips_build_artifacts(tmp_path):
    files = {
        "models/orders.sql": "select 1",
        "target/manifest.json": "{}",
        "dbt_packages/pkg/macro.sql": "x",
        "node_modules/lib/index.js": "x",
        "nested/target/run_results.json": "{}",
    }
    bare = _make_bare_with_content(tmp_path, files)
    tree = _read_repo_tree(bare, "refs/heads/main")
    assert set(tree) == {"models/orders.sql"}


def test_is_skipped_path_matches_segments_not_substrings():
    assert _is_skipped_path("target/manifest.json")
    assert _is_skipped_path("sub/dbt_packages/x.sql")
    assert not _is_skipped_path("models/targeting.sql")
    assert not _is_skipped_path("retarget/file.sql")


# ── distill_graph ────────────────────────────────────────────────────────────


def test_distill_graph_is_manifest_shaped_subset():
    manifest = {
        "metadata": {"dbt_version": "1.8.0", "project_name": "demo", "generated_at": "x"},
        "nodes": {
            "model.demo.orders": {
                "name": "orders",
                "resource_type": "model",
                "path": "orders.sql",
                "original_file_path": "models/orders.sql",
                "fqn": ["demo", "orders"],
                "schema": "main",
                "database": "db",
                "description": "d" * 900,
                "tags": ["t1"],
                "config": {"materialized": "table", "unrelated": "dropped"},
                "columns": {"id": {"name": "id", "description": "pk"}},
                "raw_code": "select * from big",  # must not survive distillation
            },
            "test.demo.not_null_orders_id": {
                "name": "not_null_orders_id",
                "resource_type": "test",
                "test_metadata": {"name": "not_null", "kwargs": {"column_name": "id"}},
            },
        },
        "sources": {
            "source.demo.raw.orders": {
                "name": "orders",
                "resource_type": "source",
                "columns": {},
            }
        },
        "parent_map": {"model.demo.orders": ["source.demo.raw.orders"]},
        "child_map": {"model.demo.orders": ["test.demo.not_null_orders_id"]},
    }
    graph = distill_graph(manifest)

    node = graph["nodes"]["model.demo.orders"]
    assert node["config"] == {"materialized": "table"}
    assert len(node["description"]) == 500
    assert node["columns"]["id"]["name"] == "id"
    assert "raw_code" not in node
    # Tests keep their metadata so per-model test chips still render.
    assert graph["nodes"]["test.demo.not_null_orders_id"]["test_metadata"]["name"] == "not_null"
    assert "source.demo.raw.orders" in graph["sources"]
    assert graph["parent_map"] == manifest["parent_map"]
    assert graph["metadata"]["dbt_version"] == "1.8.0"


def test_classify_failure():
    assert classify_failure("Runtime Error: Could not find profile named x") == "profile_missing"
    assert classify_failure("Compilation Error in model foo") == "parse_error"
    assert classify_failure("all good") is None


# ── S3 key layout ────────────────────────────────────────────────────────────


def test_dbt_keys_live_under_project_prefix():
    m = dbt_manifest_key("org", "proj", "main", 3)
    g = dbt_graph_key("org", "proj", "feature/x", 3)
    prefix = project_prefix("org", "proj")
    assert m.startswith(prefix) and m.endswith("/dbt/000000000003-manifest.json.gz")
    assert g.startswith(prefix) and g.endswith("/dbt/000000000003-graph.json.gz")
    # distinct from workspace file manifests
    assert "/manifests/" not in m


# ── trigger config resolution ────────────────────────────────────────────────


def test_watched_branches_defaults_and_override():
    assert _watched_branches({}, "main") == ["main"]
    assert _watched_branches({"watched_branches": []}, "main") == ["main"]
    assert _watched_branches({"watched_branches": ["main", "prod"]}, "x") == ["main", "prod"]
