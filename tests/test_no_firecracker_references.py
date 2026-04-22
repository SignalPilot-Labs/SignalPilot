"""Regression test: ensure no stale Firecracker/KVM/jailer references remain in the codebase.

Frontend TSX/TS files under signalpilot/web/ are excluded — those are updated in Round 3.
Documentation that mentions KVM only to explain gVisor does NOT need it is allowed.
"""

from __future__ import annotations

import re
from pathlib import Path

_FRONTEND_DIR = "signalpilot/web"


def _repo_root() -> Path:
    return Path(__file__).parent.parent


def _excluded_dirs() -> set[str]:
    return {".git", "node_modules", "__pycache__"}


def _is_excluded_path(path: Path, repo_root: Path) -> bool:
    parts = path.relative_to(repo_root).parts
    return any(part in _excluded_dirs() for part in parts)


def _is_frontend(path: Path, repo_root: Path) -> bool:
    try:
        rel = path.relative_to(repo_root / _FRONTEND_DIR)
        return True
    except ValueError:
        return False


def _collect_source_files(repo_root: Path, *, include_frontend: bool = True) -> list[Path]:
    patterns = [
        "**/*.py",
        "**/*.ts",
        "**/*.tsx",
        "**/*.yml",
        "**/*.yaml",
        "**/*.sh",
        "**/*.ps1",
        "**/Dockerfile",
        "**/Dockerfile.*",
        "**/*.md",
        "**/*.env",
        "**/*.example",
    ]
    files: list[Path] = []
    for pattern in patterns:
        for path in repo_root.rglob(pattern.removeprefix("**/")):
            if path.is_file() and not _is_excluded_path(path, repo_root):
                if not include_frontend and _is_frontend(path, repo_root):
                    continue
                files.append(path)
    return files


def _find_matches(files: list[Path], pattern: re.Pattern, exclude_paths: set[Path]) -> list[tuple[Path, int, str]]:
    matches: list[tuple[Path, int, str]] = []
    for path in files:
        if path in exclude_paths:
            continue
        try:
            text = path.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        for line_num, line in enumerate(text.splitlines(), start=1):
            if pattern.search(line):
                matches.append((path, line_num, line.strip()))
    return matches


_KVM_NEGATION_RE = re.compile(
    r"(no\s+kvm|not\s+require\s+kvm|does\s+not\s+need\s+kvm|without\s+kvm|doesn.t\s+(need|require)\s+kvm|no\s+`?/dev/kvm`?|no\s+.*kvm.*needed|does\s+not\s+require\s+kvm)",
    re.IGNORECASE,
)


def _is_kvm_negation(line: str) -> bool:
    return bool(_KVM_NEGATION_RE.search(line))


class TestNoFirecrackerReferences:
    """Ensure no stale Firecracker/KVM references remain in the codebase.

    Frontend files (signalpilot/web/) are excluded — deferred to Round 3.
    """

    def test_no_firecracker_in_source_files(self):
        repo_root = _repo_root()
        this_file = Path(__file__).resolve()
        files = _collect_source_files(repo_root, include_frontend=False)

        pattern = re.compile(r"firecracker", re.IGNORECASE)
        exclude_paths = {this_file}

        matches = _find_matches(files, pattern, exclude_paths)

        if matches:
            details = "\n".join(
                f"  {path.relative_to(repo_root)}:{line_num}: {line}"
                for path, line_num, line in matches
            )
            raise AssertionError(
                f"Found {len(matches)} 'firecracker' reference(s) in source files:\n{details}"
            )

    def test_no_kvm_in_source_files(self):
        repo_root = _repo_root()
        this_file = Path(__file__).resolve()
        metrics_py = (repo_root / "signalpilot" / "gateway" / "gateway" / "api" / "metrics.py").resolve()

        files = _collect_source_files(repo_root, include_frontend=False)

        package_lock_files = {
            path for path in files if path.name == "package-lock.json"
        }

        pattern = re.compile(r"kvm", re.IGNORECASE)
        exclude_paths = {this_file, metrics_py} | package_lock_files

        matches = _find_matches(files, pattern, exclude_paths)
        matches = [(p, n, l) for p, n, l in matches if not _is_kvm_negation(l)]

        if matches:
            details = "\n".join(
                f"  {path.relative_to(repo_root)}:{line_num}: {line}"
                for path, line_num, line in matches
            )
            raise AssertionError(
                f"Found {len(matches)} 'kvm' reference(s) in source files:\n{details}"
            )

    def test_no_jailer_in_source_files(self):
        repo_root = _repo_root()
        this_file = Path(__file__).resolve()

        files = _collect_source_files(repo_root)

        package_lock_files = {
            path for path in files if path.name == "package-lock.json"
        }

        pattern = re.compile(r"jailer", re.IGNORECASE)
        exclude_paths = {this_file} | package_lock_files

        matches = _find_matches(files, pattern, exclude_paths)

        if matches:
            details = "\n".join(
                f"  {path.relative_to(repo_root)}:{line_num}: {line}"
                for path, line_num, line in matches
            )
            raise AssertionError(
                f"Found {len(matches)} 'jailer' reference(s) in source files:\n{details}"
            )

    def test_no_firecracker_directory_exists(self):
        repo_root = _repo_root()
        firecracker_dir = repo_root / "sp-firecracker-vm"
        assert not firecracker_dir.exists(), (
            f"Directory {firecracker_dir} still exists — run: git mv sp-firecracker-vm sp-sandbox"
        )

    def test_sp_sandbox_directory_exists(self):
        repo_root = _repo_root()
        sandbox_dir = repo_root / "sp-sandbox"
        assert sandbox_dir.exists(), f"Directory {sandbox_dir} does not exist"
        assert sandbox_dir.is_dir(), f"{sandbox_dir} is not a directory"

        expected_files = [
            "Dockerfile",
            "Dockerfile.sandbox",
            "Dockerfile.test",
        ]
        for filename in expected_files:
            assert (sandbox_dir / filename).exists(), (
                f"Expected file {filename} not found in {sandbox_dir}"
            )
