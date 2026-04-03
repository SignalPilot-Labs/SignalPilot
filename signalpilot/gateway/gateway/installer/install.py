"""SignalPilot installer — main orchestration."""

import os
import subprocess
import sys
import time
from pathlib import Path

from . import checks, ui


def _find_repo_root() -> Path:
    """Walk up from this file to find the repo root (has .env.example)."""
    current = Path(__file__).resolve()
    for parent in current.parents:
        if (parent / ".env.example").exists():
            return parent
        if (parent / "signalpilot").is_dir() and (parent / ".env.example").exists():
            return parent
    # Fallback: assume standard layout (installer -> gateway -> gateway -> signalpilot -> repo)
    fallback = Path(__file__).resolve().parents[4]
    if (fallback / "signalpilot").is_dir():
        return fallback
    raise FileNotFoundError(
        "Could not locate SignalPilot repo root. "
        "Run this command from within the repository."
    )


def _compose_file(repo_root: Path, dev: bool = False) -> Path:
    docker_dir = repo_root / "signalpilot" / "docker"
    if dev:
        return docker_dir / "docker-compose.dev.yml"
    return docker_dir / "docker-compose.yml"


def _run_compose(
    compose_file: Path, *args: str, capture: bool = False
) -> subprocess.CompletedProcess:
    cmd = ["docker", "compose", "-f", str(compose_file), *args]
    if capture:
        return subprocess.run(cmd, capture_output=True, text=True, timeout=300)
    return subprocess.run(
        cmd, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE, text=True, timeout=300
    )


def _wait_for_docker(max_seconds: int = 60) -> bool:
    """Wait for Docker daemon to become available."""
    for _ in range(0, max_seconds, 2):
        try:
            result = subprocess.run(["docker", "info"], capture_output=True, timeout=5)
            if result.returncode == 0:
                return True
        except (subprocess.TimeoutExpired, OSError):
            pass
        sys.stdout.write(".")
        sys.stdout.flush()
        time.sleep(2)
    return False


def _configure_env(repo_root: Path, step: int = 0, total: int = 0) -> None:
    """Interactive .env configuration."""
    env_file = repo_root / ".env"
    example_file = repo_root / ".env.example"

    ui.section("Configuration", step, total)

    if env_file.exists():
        ui.check(".env", "already exists, skipping")
        return

    if example_file.exists():
        import shutil
        shutil.copy2(example_file, env_file)

    try:
        answer = input(f"    Configure environment now? {ui.dim_text('[y/N]')} ")
    except (EOFError, KeyboardInterrupt):
        print()
        return

    if answer.lower() not in ("y", "yes"):
        ui.hint(f"Skipped — edit {env_file} before starting services.")
        return

    print()
    try:
        repo = input(f"    {ui.bold_text('GitHub repo')} (e.g. YourOrg/SignalPilot): ")
        import getpass
        git_token = getpass.getpass(f"    {ui.bold_text('GitHub token')}: ")
        claude_token = getpass.getpass(f"    {ui.bold_text('Claude OAuth token')}: ")
    except (EOFError, KeyboardInterrupt):
        print()
        return

    print()
    ui.check("GITHUB_REPO", repo)
    if git_token:
        masked = f"****{git_token[-4:]}" if len(git_token) > 8 else "****"
        ui.check("GIT_TOKEN", masked)
    if claude_token:
        masked = f"****{claude_token[-4:]}" if len(claude_token) > 8 else "****"
        ui.check("CLAUDE_CODE_OAUTH_TOKEN", masked)

    # Read existing env file lines, replace matching keys
    lines = env_file.read_text().splitlines() if env_file.exists() else []
    replacements = {
        "GITHUB_REPO": repo,
        "GIT_TOKEN": git_token,
        "CLAUDE_CODE_OAUTH_TOKEN": claude_token,
    }

    new_lines = []
    replaced: set[str] = set()
    for line in lines:
        stripped = line.strip()
        # Skip comments and blank lines — pass through unchanged
        if not stripped or stripped.startswith("#"):
            new_lines.append(line)
            continue
        key = line.split("=")[0].strip() if "=" in line else ""
        if key in replacements:
            new_lines.append(f"{key}={replacements[key]}")
            replaced.add(key)
        else:
            new_lines.append(line)

    # Append any keys not already present in the file
    for key, val in replacements.items():
        if key not in replaced and val:
            new_lines.append(f"{key}={val}")

    env_file.write_text("\n".join(new_lines) + "\n")
    env_file.chmod(0o600)
    print()
    ui.hint(f"Written to {env_file}")


def _build_services(compose_file: Path, services: list[str], step: int = 0, total: int = 0) -> bool:
    """Build Docker services with progress display."""
    ui.section("Building", step, total)

    for svc in services:
        ui.dot(svc, "queued")

    # Move cursor up to overwrite the dot lines
    if ui.IS_TTY:
        sys.stdout.write(f"\033[{len(services)}A")
        sys.stdout.flush()

    for svc in services:
        if ui.IS_TTY:
            sys.stdout.write(f"{ui.CLEAR_LINE}")
        action_label = "pulling..." if svc == "postgres" else "building..."
        ui.wait_item(svc, action_label)

        timer = ui.Timer().start()

        spinner = ui.Spinner(f"Building {svc}")
        spinner.start()

        try:
            if svc == "postgres":
                result = _run_compose(compose_file, "pull", "postgres", capture=True)
            else:
                result = _run_compose(compose_file, "build", svc, capture=True)
        except subprocess.TimeoutExpired:
            spinner.stop()
            if ui.IS_TTY:
                sys.stdout.write(f"{ui.CURSOR_UP}{ui.CLEAR_LINE}")
            ui.fail(svc, "timed out")
            return False

        spinner.stop()

        if ui.IS_TTY:
            sys.stdout.write(f"{ui.CURSOR_UP}{ui.CLEAR_LINE}")

        if result.returncode == 0:
            action = "pulled" if svc == "postgres" else "built"
            elapsed = timer.elapsed_display()
            ui.check(svc, f"{action:<10} {ui.dim_text(elapsed)}")
        else:
            ui.fail(svc, "build failed")
            ui.error_block("Build output:", "")
            output = result.stderr or result.stdout or ""
            for line in output.strip().split("\n")[-20:]:
                print(f"      {line}")
            return False

    return True


def _start_services(compose_file: Path, step: int = 0, total: int = 0) -> bool:
    """Start services and wait for health."""
    ui.section("Starting services", step, total)

    result = _run_compose(compose_file, "up", "-d")
    if result.returncode != 0:
        ui.fail("docker compose", "failed to start")
        ui.hint(f"Run: docker compose -f {compose_file} up")
        return False

    health_services = [
        ("postgres", 5600, 60),
        ("gateway", 3300, 90),
        ("web", 3200, 90),
    ]

    for svc, port, timeout in health_services:
        spinner = ui.Spinner(f"Waiting for {svc}")
        spinner.start()

        healthy = False
        for _ in range(0, timeout, 2):
            try:
                ps_result = _run_compose(
                    compose_file, "ps", "--format", "json", svc, capture=True
                )
                output = ps_result.stdout.lower()
                if "healthy" in output or "running" in output:
                    healthy = True
                    break
            except (subprocess.TimeoutExpired, OSError):
                pass
            time.sleep(2)

        spinner.stop()

        if healthy:
            ui.check(svc, f"healthy    (localhost:{port})")
        else:
            ui.fail(svc, "did not become healthy in time")
            ui.hint(f"Check logs: docker compose -f {compose_file} logs {svc}")

    return True


def _verify_services(compose_file: Path, step: int = 0, total: int = 0) -> None:
    """Verify services are responding correctly."""
    ui.section("Verifying", step, total)

    # Gateway API health check
    status, ms = checks.verify_endpoint("http://localhost:3300/health")
    if status and 200 <= status < 300:
        ui.check("Gateway API", f"{status} OK     {ui.dim_text(f'({ms}ms)')}")
    elif status:
        ui.fail("Gateway API", f"HTTP {status}")
    else:
        ui.fail("Gateway API", "unreachable")

    # Web UI check
    status, ms = checks.verify_endpoint("http://localhost:3200")
    if status and 200 <= status < 400:
        ui.check("Web UI", f"{status} OK     {ui.dim_text(f'({ms}ms)')}")
    elif status:
        ui.fail("Web UI", f"HTTP {status}")
    else:
        ui.fail("Web UI", "unreachable")

    # PostgreSQL check
    ok, ms = checks.verify_postgres(str(compose_file))
    if ok:
        ui.check("PostgreSQL", f"connected  {ui.dim_text(f'({ms}ms)')}")
    else:
        ui.fail("PostgreSQL", "not responding")


def run_install(
    dev: bool = False,
    skip_build: bool = False,
) -> None:
    """Main install entry point."""

    ui.header()

    # Step tracking for progress display
    step = 0
    total_steps = 6  # System, Dependencies, Configuration, Building, Starting, Verifying

    def next_step() -> int:
        nonlocal step
        step += 1
        return step

    # Platform detection
    plat = checks.detect_platform()
    ui.section("System", next_step(), total_steps)
    ui.kv("OS", plat["os_pretty"])
    ui.kv("Shell", plat["shell"])
    ui.kv("User", plat["user"])

    # Dependencies
    ui.section("Dependencies", next_step(), total_steps)

    docker = checks.check_docker()

    # Docker install loop — prompt until installed
    while not docker["installed"]:
        ui.fail("Docker Desktop", "not found")
        print()
        print(f"  {ui.bold_text('Docker Desktop is required to run SignalPilot.')}")
        print()
        print(f"  Download:")
        print(f"    {ui.bold_text(plat['docker_url'])}")
        print()
        try:
            answer = input(f"    Open download page? {ui.dim_text('[y/N]')} ")
            if answer.lower() in ("y", "yes"):
                subprocess.run([plat["open_cmd"], plat["docker_url"]], capture_output=True)
        except (EOFError, KeyboardInterrupt):
            print()
            sys.exit(130)

        print()
        print(f"  {ui.dim_text('Install Docker Desktop, then press Enter...')}")
        try:
            input()
        except (EOFError, KeyboardInterrupt):
            print()
            sys.exit(130)

        docker = checks.check_docker()

    # Docker daemon check
    if not docker["running"]:
        ui.fail("Docker Desktop", "installed but not running")
        print()
        print(f"  {ui.dim_text('Start Docker Desktop, then press Enter...')}")
        try:
            input()
        except (EOFError, KeyboardInterrupt):
            print()
            sys.exit(130)

        print(f"  {ui.dim_text('Waiting for Docker daemon')}", end="", flush=True)
        if _wait_for_docker():
            print()
            docker = checks.check_docker()
        else:
            print()
            print(f"  Docker daemon still unreachable.")
            if plat["is_wsl"]:
                ui.hint(
                    "Tip: Enable 'WSL Integration' in Docker Desktop"
                    " → Settings → Resources → WSL Integration."
                )
            sys.exit(1)

    ui.check("Docker Desktop", f"v{docker['version']}")

    if docker["compose_installed"]:
        ui.check("Docker Compose", f"v{docker['compose_version']}")
    else:
        ui.fail("Docker Compose", "plugin not found")
        ui.hint("Run: docker compose version — to verify your Docker Desktop install.")
        sys.exit(1)

    # Git
    git_ver = checks.check_command("git")
    if git_ver:
        ui.check("Git", f"v{git_ver}")
    else:
        ui.fail("Git", "not found")
        ui.hint("Install from https://git-scm.com/downloads")
        sys.exit(1)

    # Port availability
    ports_ok = True
    for port in checks.REQUIRED_PORTS:
        if checks.check_port(port):
            ui.check(f"Port {port}", "available")
        else:
            owner = checks.port_owner(port)
            detail = f"in use by {owner}" if owner else "in use"
            ui.fail(f"Port {port}", detail)
            ports_ok = False

    if not ports_ok:
        ui.hint("Stop the processes using those ports and re-run.")
        sys.exit(1)

    # Resolve compose file
    repo_root = _find_repo_root()
    compose_file = _compose_file(repo_root, dev=dev)

    if not compose_file.exists():
        ui.fail("Compose file", f"not found: {compose_file}")
        sys.exit(1)

    # Configuration
    _configure_env(repo_root, next_step(), total_steps)

    # Build
    if skip_build:
        s = next_step()
        ui.section("Building", s, total_steps)
        ui.hint("Skipped (--skip-build)")
    else:
        services = ["gateway", "web", "postgres"]
        if not dev:
            services.append("sandbox")
        if not _build_services(compose_file, services, next_step(), total_steps):
            sys.exit(1)

    # Start
    if not _start_services(compose_file, next_step(), total_steps):
        ui.hint("Some services failed to start. Check logs above.")

    # Verify
    _verify_services(compose_file, next_step(), total_steps)

    # Done
    print(f"\n\n  {ui.GREEN}{ui.BOLD}✓  SignalPilot is running{ui.RESET}\n\n")
    print(f"  {'Web UI':<18}http://localhost:3200")
    print(f"  {'Gateway API':<18}http://localhost:3300")
    print(f"  {'PostgreSQL':<18}localhost:5600")
    print(f"\n\n  {ui.bold_text('Next steps')}\n")
    print(f"    1. Open {ui.bold_text('http://localhost:3200')} in your browser")
    print(f"    2. Connect a database:  {ui.dim_text('sp connect mydb postgresql://...')}")
    print(f"    3. Read the docs:       {ui.dim_text('https://github.com/SignalPilot-Labs/SignalPilot')}")
    print()
