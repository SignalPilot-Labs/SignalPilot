"""SignalPilot CLI — sp command."""

import typer
import uvicorn

app = typer.Typer(name="sp", help="SignalPilot — governed sandbox for AI database access")


@app.command()
def serve(
    host: str = typer.Option("0.0.0.0", help="Bind host"),
    port: int = typer.Option(3300, help="Bind port"),
    reload: bool = typer.Option(False, help="Auto-reload on code changes"),
):
    """Start the SignalPilot gateway server."""
    typer.echo(f"Starting SignalPilot gateway on {host}:{port}")
    uvicorn.run(
        "gateway.main:app",
        host=host,
        port=port,
        reload=reload,
        log_level="info",
    )


@app.command()
def connect(
    name: str = typer.Argument(..., help="Connection name"),
    uri: str = typer.Argument(..., help="Database URI (e.g. postgresql://user:pass@host/db)"),
    db_type: str = typer.Option("postgres", help="Database type"),
):
    """Register a database connection."""
    from .models import ConnectionCreate, DBType
    from .store import create_connection

    conn = ConnectionCreate(
        name=name,
        db_type=DBType(db_type),
        connection_string=uri,
    )
    info = create_connection(conn)
    typer.echo(f"Connection '{info.name}' registered ({info.db_type})")


@app.command()
def status():
    """Show gateway health status."""
    import httpx

    from .store import load_settings

    settings = load_settings()
    typer.echo(f"Gateway URL:         {settings.gateway_url}")
    typer.echo(f"Sandbox Manager URL: {settings.sandbox_manager_url}")
    typer.echo(f"Sandbox Provider:    {settings.sandbox_provider}")

    try:
        resp = httpx.get(f"{settings.sandbox_manager_url}/health", timeout=5)
        data = resp.json()
        typer.echo(f"Sandbox Health:      {data.get('status', 'unknown')}")
        typer.echo(f"KVM Available:       {data.get('kvm_available', False)}")
        typer.echo(f"Active VMs:          {data.get('active_vms', 0)} / {data.get('max_vms', 10)}")
    except Exception as e:
        typer.echo(f"Sandbox Health:      error — {e}")


@app.command()
def install(
    dev: bool = typer.Option(False, "--dev", help="Use dev compose file"),
    skip_build: bool = typer.Option(False, "--skip-build", help="Skip docker build step"),
    non_interactive: bool = typer.Option(False, "--non-interactive", help="Skip interactive prompts"),
    verbose: bool = typer.Option(False, "--verbose", "-v", help="Show docker compose output"),
):
    """Install and start SignalPilot using Docker Compose."""
    from .installer import run_install

    run_install(dev=dev, skip_build=skip_build, non_interactive=non_interactive, verbose=verbose)


@app.command()
def uninstall(
    dev: bool = typer.Option(False, "--dev", help="Use dev compose file"),
):
    """Stop and remove all SignalPilot containers and volumes."""
    from .installer import run_uninstall

    run_uninstall(dev=dev)


@app.command()
def doctor(
    dev: bool = typer.Option(False, "--dev", help="Check dev compose stack"),
):
    """Diagnose SignalPilot stack health."""
    from .installer import run_doctor

    run_doctor(dev=dev)


@app.command(name="config")
def show_config():
    """Show resolved configuration with source annotations."""
    from .installer.config import resolve_with_sources
    from .installer.install import _find_repo_root
    from .installer import ui

    try:
        repo_root = _find_repo_root()
    except FileNotFoundError:
        repo_root = None

    resolved = resolve_with_sources(repo_root)

    print()
    print(f"  {ui.BOLD}SignalPilot — resolved configuration{ui.RESET}")
    print()

    current_section = ""
    for flat_key in sorted(resolved):
        value, source = resolved[flat_key]
        section, key = flat_key.split(".", 1)

        if section != current_section:
            current_section = section
            print(f"  {ui.BOLD}{section}{ui.RESET}")

        # Mask sensitive values
        _SENSITIVE = {"password", "token", "secret", "api_key"}
        display_val = value
        if key in _SENSITIVE and isinstance(value, str) and len(value) > 0:
            display_val = "****"

        source_tag = f"{ui.DIM}← {source}{ui.RESET}"
        print(f"    {key:<20}{str(display_val):<20}{source_tag}")

    print()
    print(f"  {ui.DIM}Cascade: defaults → config/config.yml → ~/.signalpilot/config.yml → .signalpilot/config.yml → SP_* env{ui.RESET}")
    print()


@app.command()
def ps(
    dev: bool = typer.Option(False, "--dev", help="Use dev compose file"),
):
    """Show running SignalPilot containers."""
    from .installer.install import _compose_file, _find_repo_root

    try:
        repo_root = _find_repo_root()
    except FileNotFoundError:
        typer.echo("  Not in a SignalPilot repository.")
        raise typer.Exit(1)

    compose = _compose_file(repo_root, dev=dev)
    import subprocess

    subprocess.run(["docker", "compose", "-f", str(compose), "ps"])


@app.command()
def logs(
    service: str = typer.Argument(None, help="Service name (gateway, web, postgres)"),
    follow: bool = typer.Option(False, "--follow", "-f", help="Follow log output"),
    tail: int = typer.Option(50, "--tail", "-n", help="Number of lines to show"),
    dev: bool = typer.Option(False, "--dev", help="Use dev compose file"),
):
    """View container logs."""
    from .installer.install import _compose_file, _find_repo_root

    try:
        repo_root = _find_repo_root()
    except FileNotFoundError:
        typer.echo("  Not in a SignalPilot repository.")
        raise typer.Exit(1)

    compose = _compose_file(repo_root, dev=dev)
    import subprocess

    cmd = ["docker", "compose", "-f", str(compose), "logs", f"--tail={tail}"]
    if follow:
        cmd.append("--follow")
    if service:
        cmd.append(service)

    try:
        subprocess.run(cmd)
    except KeyboardInterrupt:
        pass


@app.command()
def version():
    """Show SignalPilot version and environment info."""
    from .installer import checks

    print()
    print(f"  SignalPilot CLI  v0.1.0")
    print()

    plat = checks.detect_platform()
    docker = checks.check_docker()

    print(f"    {'OS':<18}{plat['os_pretty']}")
    if docker["installed"]:
        print(f"    {'Docker':<18}v{docker['version']}")
    else:
        print(f"    {'Docker':<18}not installed")
    if docker["compose_installed"]:
        print(f"    {'Compose':<18}v{docker['compose_version']}")

    git_ver = checks.check_command("git")
    if git_ver:
        print(f"    {'Git':<18}v{git_ver}")

    import sys
    print(f"    {'Python':<18}{sys.version.split()[0]}")
    print()


if __name__ == "__main__":
    app()
