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
):
    """Install and start SignalPilot using Docker Compose."""
    from .installer import run_install

    run_install(dev=dev, skip_build=skip_build)


@app.command()
def doctor(
    dev: bool = typer.Option(False, "--dev", help="Check dev compose stack"),
):
    """Diagnose SignalPilot stack health."""
    from .installer import run_doctor

    run_doctor(dev=dev)


if __name__ == "__main__":
    app()
