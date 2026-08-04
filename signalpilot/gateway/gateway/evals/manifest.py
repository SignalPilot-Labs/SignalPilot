"""Parse the eval.json evaluation-set manifest.

Each manifest entry defines one read task or write task.
A read task uses the pinned MCP connection to the shared build branch.
A write task uses a disposable warehouse branch.
A write task can define setup scripts, cleanup scripts, build targets, and captures.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

DEFAULT_TOLERANCE = 0.15

VALID_CLASSES = ("read", "write")
VALID_CAPTURE_MODES = ("fingerprint", "fingerprint+sample", "full")
VALID_GRADE_KINDS = ("checks", "model_rebuilt")


class ManifestError(RuntimeError):
    """The eval repo's manifest is malformed. Message is user-facing."""


@dataclass
class EvalTask:
    id: str
    task_class: str  # "read" | "write"
    kind: str
    title: str
    why: str
    prompt: str
    doc: str
    gt: str
    checks: list[dict[str, Any]]
    grade: dict[str, Any]
    setup: str = ""  # repo-relative script, write tasks only
    teardown: str = ""
    covers: list[str] = field(default_factory=list)
    builds: list[str] = field(default_factory=list)
    capture: dict[str, Any] | None = None


@dataclass
class EvalSet:
    name: str
    description: str
    tasks: list[EvalTask]
    setup: dict[str, Any]  # script defaults: env_file, timeout_seconds
    project_repo: str = ""
    build_fingerprint: str = ""  # when set, runs refuse a mismatched warehouse
    ref: str = ""  # git commit of the eval repo checkout, stamped by the loader


def read_confined(repo_dir: Path, rel: str) -> str:
    """Read a repository-relative file that remains inside the repository.

    Reject absolute paths, parent path segments, and symbolic links outside the repository.
    """
    rel_str = str(rel)
    if not rel_str or Path(rel_str).is_absolute() or rel_str.startswith(("/", "\\")):
        raise ManifestError(f"path must be repo-relative: {rel_str!r}")
    root = repo_dir.resolve(strict=False)
    p = (repo_dir / rel_str).resolve(strict=False)
    if p != root and root not in p.parents:
        raise ManifestError(f"path escapes the eval repo: {rel_str}")
    if p.is_symlink():
        raise ManifestError(f"symlinked paths are not allowed: {rel_str}")
    return p.read_text(encoding="utf-8", errors="replace")


def _read_rel_optional(repo_dir: Path, rel: str) -> str:
    try:
        return read_confined(repo_dir, rel)
    except FileNotFoundError:
        return ""


def _require_rel_exists(repo_dir: Path, rel: str, what: str, task_id: str) -> str:
    rel_str = str(rel)
    if not rel_str or Path(rel_str).is_absolute() or rel_str.startswith(("/", "\\")):
        raise ManifestError(f"task {task_id}: {what} path must be repo-relative: {rel_str!r}")
    root = repo_dir.resolve(strict=False)
    p = (repo_dir / rel_str).resolve(strict=False)
    if p != root and root not in p.parents:
        raise ManifestError(f"task {task_id}: {what} path escapes the eval repo: {rel_str}")
    if p.is_symlink():
        raise ManifestError(f"task {task_id}: {what} may not be a symlink: {rel_str}")
    if not p.is_file():
        raise ManifestError(f"task {task_id}: {what} script not found: {rel_str}")
    return rel_str


def _parse_checks(raw: Any, default_tolerance: float, task_id: str) -> list[dict[str, Any]]:
    if not raw:
        return []
    if not isinstance(raw, list):
        raise ManifestError(f"task {task_id}: checks must be a list")
    out = []
    for c in raw:
        if not isinstance(c, dict) or "value" not in c:
            raise ManifestError(f"task {task_id}: each check needs at least a value")
        try:
            value = float(c["value"])
            tolerance = float(c.get("tolerance", default_tolerance))
        except (TypeError, ValueError) as exc:
            raise ManifestError(f"task {task_id}: non-numeric check: {exc}") from exc
        out.append({"name": str(c.get("name", "answer")), "value": value, "tolerance": tolerance})
    return out


def _checks_from_gt(gt: str, default_tolerance: float) -> list[dict[str, Any]]:
    cleaned = gt.replace(",", "").replace("$", "").strip()
    try:
        value = float(cleaned)
    except ValueError:
        return []
    return [{"name": "answer", "value": value, "tolerance": default_tolerance}]


def _parse_grade(
    raw: Any, checks: list[dict[str, Any]], task_id: str
) -> dict[str, Any]:
    """Normalize the grade block. Default: numeric checks."""
    if raw is None:
        return {"kind": "checks"}
    if not isinstance(raw, dict):
        raise ManifestError(f"task {task_id}: grade must be an object")
    kind = str(raw.get("kind", "checks"))
    if kind not in VALID_GRADE_KINDS:
        raise ManifestError(
            f"task {task_id}: unknown grade kind {kind!r} (one of {', '.join(VALID_GRADE_KINDS)})"
        )
    if kind == "model_rebuilt":
        model = str(raw.get("model", "")).strip()
        if not model:
            raise ManifestError(f"task {task_id}: grade.model_rebuilt needs a model")
        expect = raw.get("expect") or {}
        if not isinstance(expect, dict):
            raise ManifestError(f"task {task_id}: grade.expect must be an object")
        return {"kind": kind, "model": model, "expect": expect}
    return {"kind": "checks"}


def _parse_capture(raw: Any, task_class: str, builds: list[str], task_id: str) -> dict[str, Any] | None:
    if raw is None:
        return None
    if task_class != "write":
        # Read tasks do not create table captures because they do not modify the warehouse.
        raise ManifestError(f"task {task_id}: capture is only valid on write tasks")
    if not isinstance(raw, dict):
        raise ManifestError(f"task {task_id}: capture must be an object")
    tables = [str(t) for t in raw.get("tables") or builds]
    if not tables:
        raise ManifestError(f"task {task_id}: capture needs tables (or builds to default from)")
    mode = str(raw.get("mode", "fingerprint"))
    if mode not in VALID_CAPTURE_MODES:
        raise ManifestError(
            f"task {task_id}: unknown capture mode {mode!r} (one of {', '.join(VALID_CAPTURE_MODES)})"
        )
    sample_rows = int(raw.get("sample_rows", 10_000))
    if sample_rows <= 0:
        raise ManifestError(f"task {task_id}: sample_rows must be positive")
    return {"tables": tables, "mode": mode, "sample_rows": sample_rows}


def load_eval_set(repo_dir: Path) -> EvalSet:
    manifest_path = repo_dir / "eval.json"
    if not manifest_path.is_file():
        raise ManifestError(
            "no eval.json at the repo root — v2 manifests are required (see eval-format.md)"
        )
    try:
        raw = json.loads(manifest_path.read_text(encoding="utf-8"))
    except ValueError as exc:
        raise ManifestError(f"eval.json is not valid JSON: {exc}") from exc
    if not isinstance(raw, dict):
        raise ManifestError("eval.json must be a JSON object")
    if "tasks" not in raw:
        hint = " (found legacy 'questions' — rename to 'tasks', format v2)" if "questions" in raw else ""
        raise ManifestError(f"eval.json has no tasks[]{hint}")

    defaults = raw.get("defaults") or {}
    default_tolerance = float(defaults.get("tolerance", DEFAULT_TOLERANCE))
    default_class = str(defaults.get("class", "read"))
    if default_class not in VALID_CLASSES:
        raise ManifestError(f"defaults.class must be one of {', '.join(VALID_CLASSES)}")

    tasks: list[EvalTask] = []
    seen: set[str] = set()
    for entry in raw["tasks"]:
        if not isinstance(entry, dict) or not str(entry.get("id", "")).strip():
            raise ManifestError("every task needs an id")
        task_id = str(entry["id"]).strip()
        if task_id in seen:
            raise ManifestError(f"duplicate task id: {task_id}")
        seen.add(task_id)

        task_class = str(entry.get("class", default_class))
        if task_class not in VALID_CLASSES:
            raise ManifestError(
                f"task {task_id}: class must be one of {', '.join(VALID_CLASSES)}"
            )

        prompt_text = str(entry.get("prompt_text", "") or "")
        if not prompt_text:
            prompt_rel = str(entry.get("prompt", f"prompts/{task_id}.txt"))
            try:
                prompt_text = read_confined(repo_dir, prompt_rel)
            except FileNotFoundError as exc:
                raise ManifestError(f"task {task_id}: prompt file missing: {prompt_rel}") from exc

        gt = str(entry.get("gt", "") or "")
        checks = _parse_checks(entry.get("checks"), default_tolerance, task_id)
        if not checks and gt:
            checks = _checks_from_gt(gt, default_tolerance)
        grade = _parse_grade(entry.get("grade"), checks, task_id)

        builds = [str(b) for b in entry.get("builds") or []]
        covers = [str(c) for c in entry.get("covers") or []]
        if grade["kind"] == "model_rebuilt" and task_class != "write":
            raise ManifestError(f"task {task_id}: model_rebuilt grading requires class: write")
        if task_class == "write" and not builds and grade["kind"] == "model_rebuilt":
            builds = [grade["model"]]

        setup_rel = str(entry.get("setup", "") or "")
        teardown_rel = str(entry.get("teardown", "") or "")
        if (setup_rel or teardown_rel) and task_class != "write":
            raise ManifestError(
                f"task {task_id}: setup/teardown scripts are only valid on write tasks — "
                "read tasks share a branch nothing may mutate"
            )
        if setup_rel:
            setup_rel = _require_rel_exists(repo_dir, setup_rel, "setup", task_id)
        if teardown_rel:
            teardown_rel = _require_rel_exists(repo_dir, teardown_rel, "teardown", task_id)

        capture = _parse_capture(entry.get("capture"), task_class, builds, task_id)
        if capture is None and task_class == "write" and builds:
            # Always create a small fingerprint for each declared build.
            capture = {"tables": list(builds), "mode": "fingerprint", "sample_rows": 10_000}

        doc_rel = str(entry.get("doc", f"docs/{task_id}.md"))
        tasks.append(
            EvalTask(
                id=task_id,
                task_class=task_class,
                kind=str(entry.get("kind", "query")),
                title=str(entry.get("title", task_id)),
                why=str(entry.get("why", "")),
                prompt=prompt_text,
                doc=_read_rel_optional(repo_dir, doc_rel),
                gt=gt,
                checks=checks,
                grade=grade,
                setup=setup_rel,
                teardown=teardown_rel,
                covers=covers,
                builds=builds,
                capture=capture,
            )
        )

    if not tasks:
        raise ManifestError("eval.json declares no tasks")

    setup = raw.get("setup") or {}
    if not isinstance(setup, dict):
        raise ManifestError("setup must be an object")
    allowed_setup_keys = {"env_file", "timeout_seconds"}
    unknown_setup_keys = sorted(set(setup) - allowed_setup_keys)
    if unknown_setup_keys:
        raise ManifestError(
            "unsupported setup keys: " + ", ".join(unknown_setup_keys)
        )

    return EvalSet(
        name=str(raw.get("name") or repo_dir.name),
        description=str(raw.get("description", "")),
        tasks=tasks,
        setup=setup,
        project_repo=str(raw.get("project_repo", "") or ""),
        build_fingerprint=str(raw.get("build_fingerprint", "") or ""),
    )


def read_claude_md(repo_dir: Path) -> str:
    for name in ("CLAUDE.md", "claude.md"):
        text = _read_rel_optional(repo_dir, name)
        if text:
            return text
    return ""
