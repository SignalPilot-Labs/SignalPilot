"""SignalPilot doctor — diagnose stack health."""

import json
import os
import stat
import subprocess
from pathlib import Path

from . import checks, config, ui
from .install import _compose_file, _find_repo_root

# Placeholder values from .env.example that mean "not configured"
_PLACEHOLDER_PREFIXES = ("ghp_...", "github_pat_...", "sk-ant-oat01-...")

_EXPECTED_CONTAINERS = ["gateway", "web", "postgres"]

_REQUIRED_ENV_KEYS = {
    "GITHUB_REPO": "GITHUB_REPO",
    "GIT_TOKEN": "GIT_TOKEN",
    "CLAUDE_CODE_OAUTH": "CLAUDE_CODE_OAUTH_TOKEN",
}


class _DiagResult:
    """Accumulates pass/fail counts and issue descriptions."""

    def __init__(self) -> None:
        self.passed = 0
        self.failed = 0
        self.issues: list[str] = []

    def ok(self, label: str, detail: str = "") -> None:
        ui.check(label, detail)
        self.passed += 1

    def fail(self, label: str, detail: str, fix: str = "") -> None:
        ui.fail(label, detail)
        self.failed += 1
        msg = f"{label}: {detail}"
        if fix:
            msg += f" — {fix}"
        self.issues.append(msg)

    @property
    def total(self) -> int:
        return self.passed + self.failed


def _check_system(diag: _DiagResult, step: int, total: int) -> None:
    """Check system-level dependencies."""
    ui.section("System", step, total)

    plat = checks.detect_platform()
    ui.kv("OS", plat["os_pretty"])

    docker = checks.check_docker()
    if docker["installed"]:
        if checks.meets_min_version(docker["version"], checks.MIN_DOCKER_VERSION):
            diag.ok("Docker", f"v{docker['version']}")
        else:
            diag.fail("Docker", f"v{docker['version']} — requires {checks.MIN_DOCKER_VERSION}+", "update Docker Desktop")
    else:
        diag.fail("Docker", "not installed", f"install from {plat['docker_url']}")

    if docker["running"]:
        diag.ok("Docker daemon", "running")
    elif docker["installed"]:
        diag.fail("Docker daemon", "not running", "start Docker Desktop")

    if docker["compose_installed"]:
        if checks.meets_min_version(docker["compose_version"], checks.MIN_COMPOSE_VERSION):
            diag.ok("Compose", f"v{docker['compose_version']}")
        else:
            diag.fail("Compose", f"v{docker['compose_version']} — requires {checks.MIN_COMPOSE_VERSION}+", "update Docker Desktop")
    elif docker["installed"]:
        diag.fail("Compose", "plugin not found", "reinstall Docker Desktop")

    git_ver = checks.check_command("git")
    if not git_ver:
        diag.fail("Git", "not found", "install from https://git-scm.com")
    elif checks.meets_min_version(git_ver, checks.MIN_GIT_VERSION):
        diag.ok("Git", f"v{git_ver}")
    else:
        diag.fail("Git", f"v{git_ver} — requires {checks.MIN_GIT_VERSION}+", "update from https://git-scm.com")

    # Docker socket access
    docker_socket = Path("/var/run/docker.sock")
    if docker_socket.exists():
        if os.access(str(docker_socket), os.R_OK | os.W_OK):
            diag.ok("Docker socket", "accessible")
        else:
            diag.fail("Docker socket", "permission denied", "add user to docker group or chmod 660 /var/run/docker.sock")
    elif docker["installed"]:
        # Docker installed but no socket — might be using Docker Desktop's VM
        diag.ok("Docker socket", "using Docker Desktop")


def _check_configuration(diag: _DiagResult, repo_root: Path, step: int, total: int) -> None:
    """Check .env file presence, permissions, and required keys."""
    ui.section("Configuration", step, total)

    env_file = repo_root / ".env"

    if not env_file.exists():
        diag.fail(".env", "not found", f"run: cp .env.example .env")
        return

    # Check permissions
    mode = env_file.stat().st_mode
    perms = stat.S_IMODE(mode)
    if perms & (stat.S_IRGRP | stat.S_IROTH):
        diag.fail(".env", f"world-readable ({oct(perms)[-3:]})", "run: chmod 600 .env")
    else:
        diag.ok(".env", f"found ({oct(perms)[-3:]})")

    # Check required keys
    content = env_file.read_text()
    for display_name, key in _REQUIRED_ENV_KEYS.items():
        value = None
        for line in content.splitlines():
            stripped = line.strip()
            if stripped.startswith(f"{key}="):
                value = stripped.split("=", 1)[1].strip()
                break

        if not value:
            diag.fail(display_name, "not set", f"add {key}=... to .env")
        elif any(value.startswith(p) for p in _PLACEHOLDER_PREFIXES):
            diag.fail(display_name, "placeholder value", f"set a real value for {key}")
        else:
            diag.ok(display_name, "set")


def _check_containers(diag: _DiagResult, compose_file: Path, step: int, total: int) -> None:
    """Check that expected containers are running."""
    ui.section("Containers", step, total)

    try:
        result = subprocess.run(
            ["docker", "compose", "-f", str(compose_file), "ps", "--format", "json"],
            capture_output=True, text=True, timeout=15,
        )
    except (subprocess.TimeoutExpired, OSError):
        diag.fail("docker compose", "could not query containers")
        return

    if result.returncode != 0:
        diag.fail("docker compose", "ps failed", f"run: docker compose -f {compose_file} ps")
        return

    # Parse container states — docker compose ps --format json outputs one JSON object per line
    running: dict[str, str] = {}
    for line in result.stdout.strip().splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            obj = json.loads(line)
            name = obj.get("Service", obj.get("Name", ""))
            state = obj.get("State", "unknown")
            status = obj.get("Status", "")
            running[name] = f"{state}    ({status})" if status else state
        except json.JSONDecodeError:
            continue

    for svc in _EXPECTED_CONTAINERS:
        if svc in running:
            state_str = running[svc]
            if "restarting" in state_str.lower():
                diag.fail(
                    svc, "restarting",
                    f"check logs: docker compose -f {compose_file} logs {svc}",
                )
            else:
                diag.ok(svc, state_str)
        else:
            diag.fail(svc, "not running", f"run: docker compose -f {compose_file} up -d")


def _check_ports(diag: _DiagResult, cfg: dict, step: int, total: int) -> None:
    """Check that required ports are available or owned by SignalPilot containers."""
    ui.section("Ports", step, total)

    for port in checks.required_ports(cfg):
        if checks.check_port(port):
            diag.ok(f"Port {port}", "available")
        else:
            owner = checks.port_owner(port)
            # If owned by docker, it's likely our container — that's fine
            if owner and "docker" in owner.lower():
                diag.ok(f"Port {port}", f"in use by {owner} (expected)")
            elif owner:
                diag.fail(f"Port {port}", f"in use by {owner}", f"stop {owner} or change port in config")
            else:
                diag.fail(f"Port {port}", "in use", "stop the process or change port in config")


def _check_endpoints(diag: _DiagResult, cfg: dict, step: int, total: int) -> None:
    """Verify health endpoints respond correctly."""
    ui.section("Endpoints", step, total)

    gw_port = cfg.get("gateway", {}).get("port", 3300)
    web_port = cfg.get("web", {}).get("port", 3200)

    endpoints = [
        ("Gateway API", f"http://localhost:{gw_port}/health", 200, 300),
        ("Web UI", f"http://localhost:{web_port}", 200, 400),
    ]

    for label, url, expect_min, expect_max in endpoints:
        status, ms = checks.verify_endpoint(url, timeout=5)
        if status and expect_min <= status < expect_max:
            diag.ok(label, f"{status} OK     {ui.dim_text(f'({ms}ms)')}")
        elif status:
            diag.fail(label, f"HTTP {status}")
        else:
            diag.fail(label, "unreachable")


def _check_resources(diag: _DiagResult, step: int, total: int) -> None:
    """Check Docker disk usage."""
    ui.section("Resources", step, total)

    try:
        result = subprocess.run(
            ["docker", "system", "df", "--format", "json"],
            capture_output=True, text=True, timeout=15,
        )
    except (subprocess.TimeoutExpired, OSError):
        diag.fail("Docker disk", "could not query")
        return

    if result.returncode != 0:
        diag.fail("Docker disk", "query failed")
        return

    # Sum up total size from JSON lines
    total_bytes = 0
    for line in result.stdout.strip().splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            obj = json.loads(line)
            size_str = obj.get("TotalCount", obj.get("Size", "0"))
            # Docker returns human-readable sizes, just display the raw output
            reclaimable = obj.get("Reclaimable", "")
            if reclaimable:
                total_bytes += 1  # Just count entries
        except (json.JSONDecodeError, ValueError):
            continue

    # Simpler approach: just run docker system df and grab the summary
    try:
        result2 = subprocess.run(
            ["docker", "system", "df"],
            capture_output=True, text=True, timeout=15,
        )
        lines = result2.stdout.strip().splitlines()
        # Show total images size from the table
        for line in lines[1:]:
            parts = line.split()
            if parts and parts[0] == "Images":
                size = parts[3] if len(parts) > 3 else "unknown"
                unit = parts[4] if len(parts) > 4 else ""
                diag.ok("Docker disk", f"{size} {unit} used (images)")
                return
        # Fallback: just say we checked
        diag.ok("Docker disk", "accessible")
    except (subprocess.TimeoutExpired, OSError):
        diag.fail("Docker disk", "could not query")


def run_doctor(dev: bool = False) -> None:
    """Run all diagnostic checks and print a summary."""
    print()

    diag = _DiagResult()
    total_steps = 6

    try:
        repo_root = _find_repo_root()
        compose_file = _compose_file(repo_root, dev=dev)
    except FileNotFoundError:
        repo_root = Path.cwd()
        compose_file = repo_root / "signalpilot" / "docker" / "docker-compose.yml"

    cfg = config.load_config(repo_root)

    _check_system(diag, 1, total_steps)
    _check_configuration(diag, repo_root, 2, total_steps)
    _check_ports(diag, cfg, 3, total_steps)
    _check_containers(diag, compose_file, 4, total_steps)
    _check_endpoints(diag, cfg, 5, total_steps)
    _check_resources(diag, 6, total_steps)

    # Summary
    print()
    if diag.failed == 0:
        print(f"\n  {ui.GREEN}{ui.BOLD}✓  All checks passed — {diag.total}/{diag.total}{ui.RESET}\n")
    else:
        print(f"\n  ⚠  {diag.passed}/{diag.total} checks passed — {diag.failed} issue{'s' if diag.failed != 1 else ''} found\n")
        for i, issue in enumerate(diag.issues, 1):
            print(f"    {i}. {issue}")
        print()
