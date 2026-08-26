#!/usr/bin/env python3
"""Run dbt parse and surface structural errors.

Runs `dbt parse` as a subprocess against a project directory and parses the
output for errors, warnings, and orphan patches (yml-defined models with no
matching .sql file).  Produces a structured report.

Usage:
    python3 validate_project.py <project_dir> [timeout_seconds]

Example:
    python3 validate_project.py ./my_dbt_project
    python3 validate_project.py ./my_dbt_project 120

Options:
    --help   Show this help message and exit.
"""

import re
import shutil
import subprocess
import sys
import time
from pathlib import Path

# Strip ANSI escape codes
_ANSI = re.compile(r"\x1b\[[0-9;]*m")

# Parse dbt output markers
_WARNING_LINE = re.compile(r"\[WARNING\]:\s*(.+)", re.IGNORECASE)
_ERROR_LINE = re.compile(r"\[ERROR\]:\s*(.+)", re.IGNORECASE)
_ORPHAN_PATCH = re.compile(
    r"Did not find matching node for patch with name '([^']+)'",
    re.IGNORECASE,
)

_DEFAULT_TIMEOUT = 60


def validate(project_dir: Path, timeout: int = _DEFAULT_TIMEOUT) -> dict:
    """Run dbt parse and return structured results."""
    if not project_dir.exists():
        return {
            "success": False,
            "errors": [f"project directory does not exist: {project_dir}"],
            "warnings": [],
            "orphan_patches": [],
            "parse_time_ms": 0.0,
            "mode": "project_missing",
        }

    dbt_bin = shutil.which("dbt")
    if dbt_bin is None:
        return {
            "success": False,
            "errors": ["dbt executable not found on PATH"],
            "warnings": [],
            "orphan_patches": [],
            "parse_time_ms": 0.0,
            "mode": "dbt_not_installed",
        }

    t0 = time.perf_counter()
    try:
        completed = subprocess.run(
            [dbt_bin, "parse"],
            cwd=str(project_dir),
            capture_output=True,
            text=True,
            timeout=max(1, min(timeout, 300)),
            stdin=subprocess.DEVNULL,
        )
    except subprocess.TimeoutExpired:
        return {
            "success": False,
            "errors": [f"dbt parse timed out after {timeout}s"],
            "warnings": [],
            "orphan_patches": [],
            "parse_time_ms": (time.perf_counter() - t0) * 1000.0,
            "mode": "timeout",
        }
    except FileNotFoundError:
        return {
            "success": False,
            "errors": ["dbt executable could not be launched"],
            "warnings": [],
            "orphan_patches": [],
            "parse_time_ms": (time.perf_counter() - t0) * 1000.0,
            "mode": "dbt_not_installed",
        }

    elapsed_ms = (time.perf_counter() - t0) * 1000.0
    combined = (completed.stdout or "") + "\n" + (completed.stderr or "")
    clean = _ANSI.sub("", combined)

    warnings = []
    errors = []
    orphan_patches = []

    for line in clean.splitlines():
        line = line.strip()
        if not line:
            continue

        w = _WARNING_LINE.search(line)
        if w:
            warnings.append(w.group(1).strip())
            orphan = _ORPHAN_PATCH.search(line)
            if orphan:
                orphan_patches.append(orphan.group(1))
            continue

        e = _ERROR_LINE.search(line)
        if e:
            errors.append(e.group(1).strip())

    # If returncode nonzero but no errors captured, grab tail of output
    if completed.returncode != 0 and not errors:
        log_prefix = re.compile(r"^\d{2}:\d{2}:\d{2}\s+")
        tail = []
        for raw in clean.splitlines():
            stripped = raw.strip()
            if not stripped:
                continue
            if log_prefix.match(stripped):
                rest = log_prefix.sub("", stripped)
                if rest.lower().startswith(("running with", "registered adapter", "encountered an error")):
                    continue
            tail.append(stripped)
        tail = tail[-10:]
        if tail:
            errors.append("\n".join(tail))

    # Detect failure mode
    mode = "ok"
    if completed.returncode != 0:
        lowered = clean.lower()
        if any(p in lowered for p in ("could not find profile", "profiles.yml", "not find profile")):
            mode = "profile_missing"
        elif any(p in lowered for p in ("could not find package", "not installed", "missing package")):
            mode = "packages_missing"
        elif any(p in lowered for p in ("parsing error", "compilation error")):
            mode = "parse_failed"
        else:
            mode = f"exit_{completed.returncode}"

    success = completed.returncode == 0 and not errors

    return {
        "success": success,
        "errors": errors,
        "warnings": warnings,
        "orphan_patches": sorted(set(orphan_patches)),
        "parse_time_ms": elapsed_ms,
        "mode": mode,
    }


def format_report(result: dict) -> str:
    """Format validation result as a readable report."""
    lines = ["# dbt parse validation"]
    status = "PASS" if result["success"] else "FAIL"
    lines.append(f"Status: {status} ({result['mode']})")
    lines.append(f"Parse time: {result['parse_time_ms']:.0f}ms")
    lines.append(f"Errors: {len(result['errors'])}  Warnings: {len(result['warnings'])}")
    if result["orphan_patches"]:
        lines.append(f"Orphan patches: {len(result['orphan_patches'])}")
    lines.append("")

    if result["errors"]:
        lines.append("## Errors")
        for err in result["errors"][:20]:
            lines.append(f"  - {err}")
        if len(result["errors"]) > 20:
            lines.append(f"  (+{len(result['errors']) - 20} more)")
        lines.append("")

    if result["orphan_patches"]:
        lines.append("## Orphan patches (yml-defined models with no .sql file)")
        for name in result["orphan_patches"][:40]:
            lines.append(f"  - {name}")
        if len(result["orphan_patches"]) > 40:
            lines.append(f"  (+{len(result['orphan_patches']) - 40} more)")
        lines.append("")

    non_orphan = [w for w in result["warnings"] if "Did not find matching node for patch" not in w]
    if non_orphan:
        lines.append("## Other warnings")
        for w in non_orphan[:20]:
            lines.append(f"  - {w}")
        if len(non_orphan) > 20:
            lines.append(f"  (+{len(non_orphan) - 20} more)")
        lines.append("")

    if not result["success"]:
        hints = {
            "profile_missing": "Fix profiles.yml - dbt cannot find a valid profile.",
            "packages_missing": "Run `dbt deps` to install referenced packages.",
            "parse_failed": "Inspect the errors above - yml syntax or Jinja error.",
            "dbt_not_installed": "Install dbt and ensure it's on PATH.",
            "timeout": "dbt parse exceeded the timeout - project may be very large.",
            "project_missing": "The project directory does not exist.",
        }
        hint = hints.get(result["mode"], "Inspect the errors above and address them.")
        lines.append(f"## Next step")
        lines.append(hint)
        lines.append("")

    return "\n".join(lines)


def main() -> int:
    if "--help" in sys.argv or "-h" in sys.argv:
        print(__doc__.strip())
        return 0

    if len(sys.argv) < 2:
        print("Usage: python3 validate_project.py <project_dir> [timeout_seconds]")
        print("Run with --help for more details.")
        return 1

    project = Path(sys.argv[1])
    timeout = int(sys.argv[2]) if len(sys.argv) > 2 else _DEFAULT_TIMEOUT

    if not project.is_absolute():
        project = Path.cwd() / project

    result = validate(project, timeout)
    print(format_report(result))

    return 0 if result["success"] else 1


if __name__ == "__main__":
    sys.exit(main())
