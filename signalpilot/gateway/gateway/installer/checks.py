"""Dependency and platform checks."""

import os
import platform
import re
import shutil
import socket
import subprocess
import time


def detect_platform() -> dict:
    """Detect OS, architecture, shell, user."""
    system = platform.system()
    arch = platform.machine()

    # Normalize arch
    if arch in ("x86_64", "AMD64"):
        arch = "x86_64"
    elif arch in ("aarch64", "arm64"):
        arch = "arm64"

    # Detect WSL
    is_wsl = False
    if system == "Linux":
        try:
            with open("/proc/version") as f:
                if "microsoft" in f.read().lower():
                    is_wsl = True
        except OSError:
            pass

    if is_wsl:
        os_name = "WSL2"
        os_pretty = f"Linux (WSL2, {arch})"
        docker_url = "https://docs.docker.com/desktop/setup/install/windows-install/"
        open_cmd = "explorer.exe"
    elif system == "Darwin":
        os_name = "macOS"
        mac_ver = platform.mac_ver()[0]
        os_pretty = f"macOS {mac_ver} ({arch})"
        docker_url = "https://docs.docker.com/desktop/setup/install/mac-install/"
        open_cmd = "open"
    else:
        os_name = "Linux"
        try:
            import distro  # type: ignore
            os_pretty = f"{distro.name()} {distro.version()} ({arch})"
        except ImportError:
            os_pretty = f"Linux ({arch})"
        docker_url = "https://docs.docker.com/desktop/setup/install/linux/"
        open_cmd = "xdg-open"

    shell = os.path.basename(os.environ.get("SHELL", "unknown"))
    user = os.environ.get("USER", os.environ.get("USERNAME", "unknown"))

    return {
        "os": os_name,
        "os_pretty": os_pretty,
        "arch": arch,
        "shell": shell,
        "user": user,
        "docker_url": docker_url,
        "open_cmd": open_cmd,
        "is_wsl": is_wsl,
    }


def check_command(cmd: str, version_flag: str = "--version") -> str | None:
    """Check if a command exists and return its version, or None."""
    path = shutil.which(cmd)
    if not path:
        return None
    try:
        result = subprocess.run(
            [cmd, version_flag],
            capture_output=True, text=True, timeout=10,
        )
        output = result.stdout or result.stderr
        match = re.search(r"(\d+\.\d+[\.\d]*)", output)
        return match.group(1) if match else "installed"
    except (subprocess.TimeoutExpired, OSError):
        return "installed"


def check_docker() -> dict:
    """Check Docker installation, daemon status, and compose plugin."""
    result = {
        "installed": False,
        "running": False,
        "version": None,
        "compose_installed": False,
        "compose_version": None,
    }

    docker_ver = check_command("docker")
    if not docker_ver:
        return result

    result["installed"] = True
    result["version"] = docker_ver

    # Check daemon
    try:
        proc = subprocess.run(
            ["docker", "info"],
            capture_output=True, timeout=10,
        )
        result["running"] = proc.returncode == 0
    except (subprocess.TimeoutExpired, OSError):
        pass

    # Check compose v2
    try:
        proc = subprocess.run(
            ["docker", "compose", "version"],
            capture_output=True, text=True, timeout=10,
        )
        if proc.returncode == 0:
            result["compose_installed"] = True
            match = re.search(r"(\d+\.\d+[\.\d]*)", proc.stdout)
            result["compose_version"] = match.group(1) if match else "installed"
    except (subprocess.TimeoutExpired, OSError):
        pass

    return result


def check_port(port: int) -> bool:
    """Return True if port is available."""
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.settimeout(1)
        try:
            s.bind(("127.0.0.1", port))
            return True
        except OSError:
            return False


def port_owner(port: int) -> str | None:
    """Try to identify which process owns a port."""
    try:
        result = subprocess.run(
            ["lsof", "-iTCP:%d" % port, "-sTCP:LISTEN", "-n", "-P"],
            capture_output=True, text=True, timeout=5,
        )
        lines = result.stdout.strip().split("\n")
        if len(lines) > 1:
            return lines[1].split()[0]
    except (OSError, IndexError):
        pass
    return None


REQUIRED_PORTS = [3200, 3300, 3400, 3401, 5600]


def verify_endpoint(url: str, timeout: int = 10) -> tuple[int | None, int]:
    """Hit a URL and return (status_code, elapsed_ms). Returns (None, 0) on failure."""
    import urllib.request
    import urllib.error

    start = time.perf_counter()
    try:
        req = urllib.request.Request(url, method="GET")
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            elapsed = int((time.perf_counter() - start) * 1000)
            return resp.status, elapsed
    except urllib.error.HTTPError as e:
        elapsed = int((time.perf_counter() - start) * 1000)
        return e.code, elapsed
    except (urllib.error.URLError, OSError, TimeoutError):
        elapsed = int((time.perf_counter() - start) * 1000)
        return None, elapsed


def verify_postgres(compose_file: str, timeout: int = 5) -> tuple[bool, int]:
    """Check PostgreSQL connectivity via docker compose exec. Returns (ok, elapsed_ms)."""
    start = time.perf_counter()
    try:
        result = subprocess.run(
            ["docker", "compose", "-f", compose_file, "exec", "-T", "postgres",
             "pg_isready", "-U", "postgres"],
            capture_output=True, timeout=timeout,
        )
        elapsed = int((time.perf_counter() - start) * 1000)
        return result.returncode == 0, elapsed
    except (subprocess.TimeoutExpired, OSError):
        elapsed = int((time.perf_counter() - start) * 1000)
        return False, elapsed
