"""Spider2 submission packager.

Builds the submission folder structure required by Spider2 maintainers
(submission to lfy79001@gmail.com):

    submission/
    ├── sql/{instance_id}.sql
    ├── csv/{instance_id}.csv
    └── reasoning_traces/{instance_id}.md

Reasoning traces are rendered from each task's agent_output.json transcript as
readable markdown so a human reviewer can follow what the agent did.

Usage:
    python -m benchmark.submission build --suite spider2-lite --out submission/
    python -m benchmark.submission build --suite spider2-lite --out submission/ --tasks local074 local077
    python -m benchmark.submission build --suite spider2-lite --out submission/ --tar
"""

from __future__ import annotations

import argparse
import json
import shutil
import sys
import tarfile
from pathlib import Path

from .core.suite import BenchmarkSuite, get_suite_config


_PREVIEW_LIMIT = 4000  # chars per tool-result block in trace


def _truncate(text: str, limit: int = _PREVIEW_LIMIT) -> str:
    if len(text) <= limit:
        return text
    return text[:limit] + f"\n... [truncated {len(text) - limit} chars]"


def _render_trace(instance_id: str, transcript: list[dict]) -> str:
    """Render an agent transcript as readable markdown."""
    lines = [f"# Reasoning trace: {instance_id}", ""]

    current_turn = -1
    for event in transcript:
        turn = event.get("turn", 0)
        etype = event.get("type", "?")

        if turn != current_turn and etype not in ("system",) and turn >= 1:
            current_turn = turn
            lines.append(f"\n## Turn {turn}")

        if etype == "system":
            subtype = event.get("subtype", "")
            if subtype == "init":
                continue  # skip noisy init blocks
            lines.append(f"\n_System event: {subtype}_")
        elif etype == "thinking":
            content = event.get("content", "").strip()
            if not content:
                continue
            lines.append("\n**Thinking:**\n")
            lines.append("> " + content.replace("\n", "\n> "))
        elif etype == "text":
            content = event.get("content", "").strip()
            if content:
                lines.append(f"\n**Agent:**\n\n{content}")
        elif etype == "tool_use":
            name = event.get("name", "?")
            inp = event.get("input", {})
            lines.append(f"\n**Tool call: `{name}`**\n")
            try:
                inp_str = json.dumps(inp, indent=2, default=str)
            except Exception:
                inp_str = str(inp)
            lines.append("```json")
            lines.append(_truncate(inp_str))
            lines.append("```")
        elif etype in ("tool_result", "tool_use_result"):
            content = event.get("content", "")
            if isinstance(content, (dict, list)):
                content = json.dumps(content, indent=2, default=str)
            lines.append("\n**Result:**\n")
            lines.append("```")
            lines.append(_truncate(str(content)))
            lines.append("```")
        elif etype == "user_text":
            content = event.get("content", "").strip()
            if content:
                lines.append(f"\n**User:**\n\n{content}")
        elif etype == "rate_limit":
            continue  # noise
        elif etype == "stream_event":
            continue  # noise
        elif etype == "result":
            stop = event.get("stop_reason", "?")
            n = event.get("num_turns", "?")
            cost = event.get("total_cost_usd", None)
            cost_str = f"${cost:.4f}" if isinstance(cost, (int, float)) else "n/a"
            lines.append(f"\n---\n_End of run — stop_reason={stop}, turns={n}, cost={cost_str}_")

    return "\n".join(lines) + "\n"


def _has_required_artifacts(work_dir: Path) -> bool:
    return (work_dir / "result.sql").exists() and (work_dir / "result.csv").exists()


def build_submission(
    suite: BenchmarkSuite,
    out_dir: Path,
    only_tasks: list[str] | None = None,
    make_tar: bool = False,
    method_name: str = "SignalPilot",
) -> dict:
    """Build the submission folder. Returns a manifest dict."""
    config = get_suite_config(suite)
    workroot = config.work_dir

    sql_dir = out_dir / "sql"
    csv_dir = out_dir / "csv"
    trace_dir = out_dir / "reasoning_traces"
    for d in (sql_dir, csv_dir, trace_dir):
        d.mkdir(parents=True, exist_ok=True)

    if only_tasks:
        candidates = [(t, workroot / t) for t in only_tasks]
    else:
        candidates = sorted((p.name, p) for p in workroot.iterdir() if p.is_dir())

    included: list[str] = []
    skipped: list[tuple[str, str]] = []

    for instance_id, work_dir in candidates:
        if not _has_required_artifacts(work_dir):
            skipped.append((instance_id, "missing result.sql or result.csv"))
            continue

        shutil.copyfile(work_dir / "result.sql", sql_dir / f"{instance_id}.sql")
        shutil.copyfile(work_dir / "result.csv", csv_dir / f"{instance_id}.csv")

        trace_path = work_dir / "agent_output.json"
        if trace_path.exists():
            try:
                payload = json.loads(trace_path.read_text())
                transcript = payload.get("transcript", [])
                md = _render_trace(instance_id, transcript)
            except Exception as e:
                md = f"# Reasoning trace: {instance_id}\n\n_Error rendering trace: {e}_\n"
        else:
            md = f"# Reasoning trace: {instance_id}\n\n_No agent_output.json available._\n"
        (trace_dir / f"{instance_id}.md").write_text(md)

        included.append(instance_id)

    manifest = {
        "method_name": method_name,
        "suite": suite.value,
        "n_included": len(included),
        "n_skipped": len(skipped),
        "included": included,
        "skipped": [{"id": i, "reason": r} for i, r in skipped],
    }
    (out_dir / "manifest.json").write_text(json.dumps(manifest, indent=2))

    if make_tar:
        tar_path = out_dir.with_suffix(".tar.gz")
        with tarfile.open(tar_path, "w:gz") as tar:
            tar.add(out_dir, arcname=out_dir.name)
        manifest["tarball"] = str(tar_path)

    return manifest


def main() -> None:
    parser = argparse.ArgumentParser(description="Spider2 submission packager.")
    sub = parser.add_subparsers(dest="cmd", required=True)

    b = sub.add_parser("build", help="Build a submission folder.")
    b.add_argument("--suite", default="spider2-lite", choices=["spider2-lite", "spider2-snowflake"])
    b.add_argument("--out", required=True, help="Output directory (will be created)")
    b.add_argument("--tasks", nargs="*", help="Only include these instance ids (default: all in workdir)")
    b.add_argument("--tar", action="store_true", help="Also produce <out>.tar.gz")
    b.add_argument("--method-name", default="SignalPilot", help="Name to record in manifest.json")

    args = parser.parse_args()

    if args.cmd == "build":
        suite = BenchmarkSuite(args.suite)
        out_dir = Path(args.out)
        manifest = build_submission(
            suite=suite,
            out_dir=out_dir,
            only_tasks=args.tasks,
            make_tar=args.tar,
            method_name=args.method_name,
        )
        print(f"\nIncluded: {manifest['n_included']} tasks")
        print(f"Skipped:  {manifest['n_skipped']} tasks")
        if manifest["skipped"]:
            for entry in manifest["skipped"][:10]:
                print(f"  - {entry['id']}: {entry['reason']}")
            if len(manifest["skipped"]) > 10:
                print(f"  ... and {len(manifest['skipped']) - 10} more")
        print(f"Manifest: {out_dir / 'manifest.json'}")
        if "tarball" in manifest:
            print(f"Tarball:  {manifest['tarball']}")
        sys.exit(0)


if __name__ == "__main__":
    main()
