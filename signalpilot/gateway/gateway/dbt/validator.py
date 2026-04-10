"""
dbt parse wrapper — structural validation for a dbt project.

`dbt parse` is the cheapest form of validation: it resolves Jinja, walks the
project, and produces target/manifest.json without running any SQL. It will
fail with clear errors when:
  - packages aren't installed (run `dbt deps` first)
  - profiles.yml is missing or invalid
  - a yml file has bad syntax
  - a ref() points to a model that dbt can't find (after yml processing)
  - Jinja in any .sql file is broken

This module runs it as a subprocess, parses the output into structured
errors/warnings/orphan-patches, and returns a ValidationResult. It also
detects the specific failure modes (dbt not on PATH, no profile, etc.) so
the caller can give the agent a helpful hint about what to fix.

Shelling out is necessary because dbt's Python API requires full config
setup that's identical in complexity to running the CLI. The CLI is
versioned and stable; its stdout/stderr format is the observable interface.
"""

from __future__ import annotations

import re
import shutil
import subprocess
import time
from pathlib import Path

from .types import ValidationResult

# Regex patterns to extract semantic events from dbt output.
# dbt prefixes log lines with ANSI escapes + timestamps like:
#   "\x1b[0m14:56:54  [WARNING]: ..."
# We strip ANSI first, then look for WARNING / ERROR markers.

_ANSI = re.compile(r"\x1b\[[0-9;]*m")
_WARNING_LINE = re.compile(r"\[WARNING\]:\s*(.+)", re.IGNORECASE)
_ERROR_LINE = re.compile(r"\[ERROR\]:\s*(.+)", re.IGNORECASE)

# Orphan patch warnings tell us about missing-model yml entries —
# these are the ghost entries where yml defines a model but no .sql exists.
_ORPHAN_PATCH = re.compile(
    r"Did not find matching node for patch with name '([^']+)'",
    re.IGNORECASE,
)

# Detection of specific failure modes — matched against raw output.
_PATTERNS_NO_PROFILE = ("Could not find profile", "profiles.yml", "not find profile")
_PATTERNS_NO_PACKAGE = ("Compilation Error", "could not find package", "not installed", "Missing package")
_PATTERNS_PARSE_FAIL = ("Encountered an error", "Parsing Error", "Compilation Error")

_DBT_TIMEOUT_DEFAULT = 60  # seconds


def validate_project(
    project_dir: str | Path,
    dbt_bin: str | None = None,
    timeout: int = _DBT_TIMEOUT_DEFAULT,
) -> ValidationResult:
    """Run `dbt parse` against the project and return structured results.

    Args:
        project_dir: path to the dbt project root
        dbt_bin: optional path to the dbt executable (default: search PATH)
        timeout: subprocess timeout in seconds

    Returns:
        ValidationResult — always non-raising
    """
    project_dir = Path(project_dir)

    if not project_dir.exists():
        return ValidationResult(
            success=False,
            parse_time_ms=0.0,
            error_count=1,
            warning_count=0,
            errors=[f"project directory does not exist: {project_dir}"],
            degradation_mode="project_missing",
        )

    dbt_bin = dbt_bin or shutil.which("dbt") or "dbt"
    if not shutil.which(dbt_bin) and not Path(dbt_bin).exists():
        return ValidationResult(
            success=False,
            parse_time_ms=0.0,
            error_count=1,
            warning_count=0,
            errors=[f"dbt executable not found: {dbt_bin}"],
            degradation_mode="dbt_not_installed",
        )

    t0 = time.perf_counter()
    try:
        # stdin=DEVNULL is critical: when this function is called from inside
        # an MCP stdio server, the parent's stdin is the MCP JSON-RPC channel
        # and inheriting it can hang the child (dbt briefly touches stdin on
        # some codepaths). Close it explicitly.
        completed = subprocess.run(
            [dbt_bin, "parse"],
            cwd=str(project_dir),
            capture_output=True,
            text=True,
            timeout=timeout,
            stdin=subprocess.DEVNULL,
        )
    except subprocess.TimeoutExpired as e:
        return ValidationResult(
            success=False,
            parse_time_ms=(time.perf_counter() - t0) * 1000.0,
            error_count=1,
            warning_count=0,
            errors=[f"dbt parse timed out after {timeout}s"],
            degradation_mode="timeout",
            raw_stdout=e.stdout or "",
            raw_stderr=e.stderr or "",
        )
    except FileNotFoundError:
        return ValidationResult(
            success=False,
            parse_time_ms=(time.perf_counter() - t0) * 1000.0,
            error_count=1,
            warning_count=0,
            errors=[f"dbt executable could not be launched: {dbt_bin}"],
            degradation_mode="dbt_not_installed",
        )
    except OSError as e:
        return ValidationResult(
            success=False,
            parse_time_ms=(time.perf_counter() - t0) * 1000.0,
            error_count=1,
            warning_count=0,
            errors=[f"OS error launching dbt: {e}"],
            degradation_mode="launch_failed",
        )

    elapsed_ms = (time.perf_counter() - t0) * 1000.0
    return _build_result(completed, project_dir, elapsed_ms)


def _build_result(
    completed: subprocess.CompletedProcess,
    project_dir: Path,
    elapsed_ms: float,
) -> ValidationResult:
    stdout = completed.stdout or ""
    stderr = completed.stderr or ""
    combined = stdout + "\n" + stderr

    clean = _ANSI.sub("", combined)

    warnings: list[str] = []
    errors: list[str] = []
    orphan_patches: list[str] = []

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
            continue

    # If the return code is nonzero but we haven't captured any errors from
    # markers, treat the non-empty stderr tail as the error payload — but
    # drop log-prefix noise ("HH:MM:SS  Running with dbt=...") and keep only
    # lines that look like actual diagnostics.
    if completed.returncode != 0 and not errors:
        log_prefix = re.compile(r"^\d{2}:\d{2}:\d{2}\s+")
        tail: list[str] = []
        for raw in clean.splitlines():
            stripped = raw.strip()
            if not stripped:
                continue
            # Skip startup banner lines
            if log_prefix.match(stripped):
                rest = log_prefix.sub("", stripped)
                if rest.lower().startswith(("running with", "registered adapter", "encountered an error")):
                    continue
            tail.append(stripped)
        tail = tail[-10:]  # last 10 meaningful lines
        if tail:
            errors.append("\n".join(tail))

    degradation = _detect_degradation_mode(clean, completed.returncode, project_dir)
    success = completed.returncode == 0 and not errors

    manifest_path = project_dir / "target" / "manifest.json"
    if success and not manifest_path.exists():
        # `dbt parse` succeeded but didn't write a manifest — unusual, flag it.
        success = False
        errors.append("dbt parse returned 0 but target/manifest.json was not produced")
        degradation = "manifest_missing"

    return ValidationResult(
        success=success,
        parse_time_ms=elapsed_ms,
        error_count=len(errors),
        warning_count=len(warnings),
        errors=errors,
        warnings=warnings,
        orphan_patches=sorted(set(orphan_patches)),
        degradation_mode=degradation,
        raw_stdout=stdout[-4000:],   # cap so large dumps don't balloon the result
        raw_stderr=stderr[-4000:],
    )


def _detect_degradation_mode(clean_output: str, returncode: int, project_dir: Path) -> str:
    """Classify the failure mode from dbt's output."""
    if returncode == 0:
        return "ok"

    lowered = clean_output.lower()

    if any(p.lower() in lowered for p in _PATTERNS_NO_PROFILE):
        return "profile_missing"
    if any(p.lower() in lowered for p in _PATTERNS_NO_PACKAGE):
        if "run `dbt deps`" in lowered or "dbt deps" in lowered or "package" in lowered:
            return "packages_missing"
    if any(p.lower() in lowered for p in _PATTERNS_PARSE_FAIL):
        return "parse_failed"

    return f"exit_{returncode}"


def format_validation_result(result: ValidationResult) -> str:
    """Render a ValidationResult as compact markdown for the agent."""
    lines: list[str] = ["# dbt parse validation"]
    status_icon = "✓" if result.success else "✗"
    lines.append(f"Status: {status_icon} {result.degradation_mode}")
    lines.append(f"Parse time: {result.parse_time_ms:.0f}ms")
    lines.append(f"Errors: {result.error_count}  Warnings: {result.warning_count}")
    if result.orphan_patches:
        lines.append(
            f"Orphan patches (yml entries with no matching .sql file): "
            f"{len(result.orphan_patches)}"
        )
    lines.append("")

    if result.errors:
        lines.append("## Errors")
        for err in result.errors[:20]:
            lines.append(f"  • {err}")
        if len(result.errors) > 20:
            lines.append(f"  (+{len(result.errors) - 20} more)")
        lines.append("")

    if result.orphan_patches:
        lines.append("## Orphan patches (these yml-defined models have no .sql file)")
        for name in result.orphan_patches[:40]:
            lines.append(f"  • {name}")
        if len(result.orphan_patches) > 40:
            lines.append(f"  (+{len(result.orphan_patches) - 40} more)")
        lines.append("")

    if result.warnings:
        non_orphan_warnings = [
            w for w in result.warnings
            if "Did not find matching node for patch" not in w
        ]
        if non_orphan_warnings:
            lines.append("## Other warnings")
            for w in non_orphan_warnings[:20]:
                lines.append(f"  • {w}")
            if len(non_orphan_warnings) > 20:
                lines.append(f"  (+{len(non_orphan_warnings) - 20} more)")
            lines.append("")

    if not result.success:
        lines.append("## Next step")
        lines.append(_next_step_hint(result.degradation_mode))
        lines.append("")

    return "\n".join(lines).rstrip() + "\n"


def _next_step_hint(mode: str) -> str:
    hints = {
        "profile_missing":   "Fix profiles.yml — dbt cannot find a valid profile.",
        "packages_missing":  "Run `dbt deps` to install referenced packages before parsing.",
        "parse_failed":      "Inspect the errors above — yml syntax or Jinja error.",
        "dbt_not_installed": "Install dbt and ensure it's on PATH.",
        "timeout":           "dbt parse exceeded the timeout — the project may be very large or stuck.",
        "manifest_missing":  "dbt parse succeeded but produced no manifest — check target/ is writable.",
        "project_missing":   "The project directory does not exist.",
    }
    return hints.get(mode, "Inspect the errors above and address them.")
