from __future__ import annotations

import logging
from pathlib import Path

import typer
from rich.console import Console
from rich.table import Table
from rich.panel import Panel
from rich.pretty import Pretty

from .logging_config import configure_logging
from . import __version__
from .docker_service import DockerService
from .config import ConfigManager
from .utils.system_metrics import HostMetricsProvider
from .tui.app import DashboardRunner, MenuApp
from .network_service import NetworkService
from .incident import IncidentExporter

app = typer.Typer(add_completion=False, help="Docker + Compose management CLI with live dashboard + drill-down menu.")
log = logging.getLogger(__name__)

@app.callback()
def main(
    version: bool = typer.Option(False, "--version", help="Show version and exit", is_eager=True),
):
    if version:
        Console().print(__version__)
        raise typer.Exit()


def _common_setup(level: str) -> Console:
    configure_logging(level)
    return Console()


@app.command()
def dashboard(
    refresh: float = typer.Option(1.0, help="Refresh interval seconds"),
    read_only: bool = typer.Option(True, help="Disable operational actions"),
    disk_path: str = typer.Option("/", help="Disk path to report usage for"),
    no_gpu: bool = typer.Option(False, help="Disable GPU detection"),
):
    """Live dashboard (Ctrl+C to exit)."""
    console = _common_setup("INFO")
    docker = DockerService()
    metrics = HostMetricsProvider(disk_path=disk_path, include_gpu=not no_gpu)
    DashboardRunner(docker, metrics, console=console).run(refresh_s=refresh, read_only=read_only)


@app.command()
def menu(
    read_only: bool = typer.Option(True, help="Disable operational actions (recommended)"),
    disk_path: str = typer.Option("/", help="Disk path to report usage for"),
    no_gpu: bool = typer.Option(False, help="Disable GPU detection"),
):
    """Interactive menu (dashboard + drill-down + compose projects + guardrails)."""
    console = _common_setup("INFO")
    docker = DockerService()
    metrics = HostMetricsProvider(disk_path=disk_path, include_gpu=not no_gpu)
    MenuApp(docker, metrics, console=console).run(read_only=read_only)


@app.command()
def ps(all: bool = typer.Option(True, help="Show all containers (including stopped)")):
    """List containers."""
    console = _common_setup("INFO")
    docker = DockerService()
    rows = docker.list_containers(all=all)

    tbl = Table(title="Containers", show_lines=False)
    tbl.add_column("Name")
    tbl.add_column("Project")
    tbl.add_column("Service")
    tbl.add_column("State")
    tbl.add_column("Health")
    tbl.add_column("Ports", overflow="fold")
    for c in rows:
        ports = ", ".join([f"{cp}->{hp}" for (cp, hp) in [p.as_tuple() for p in c.ports][:6]]) or "-"
        tbl.add_row(c.name, c.compose_project or "-", c.compose_service or "-", c.state, c.health, ports)
    console.print(tbl)


@app.command()
def ports():
    """List port mappings for containers."""
    console = _common_setup("INFO")
    docker = DockerService()
    containers = docker.list_containers(all=True)

    tbl = Table(title="Port mappings", show_lines=False)
    tbl.add_column("Container", no_wrap=True)
    tbl.add_column("Project", no_wrap=True)
    tbl.add_column("Service", no_wrap=True)
    tbl.add_column("Mapping", overflow="fold")
    for c in containers:
        if not c.ports:
            continue
        mappings = "; ".join([f"{cp} -> {hp}" for (cp, hp) in [p.as_tuple() for p in c.ports]])
        tbl.add_row(c.name, c.compose_project or "-", c.compose_service or "-", mappings)
    console.print(tbl)


@app.command()
def logs(
    container: str = typer.Argument(..., help="Container name or ID"),
    tail: int = typer.Option(200, help="Tail lines"),
):
    """Tail container logs."""
    console = _common_setup("INFO")
    docker = DockerService()
    console.print(Panel(docker.logs(container, tail=tail), title=f"Logs: {container}"))


@app.command()
def inspect(
    container: str = typer.Argument(..., help="Container name or ID"),
):
    """Inspect container JSON."""
    console = _common_setup("INFO")
    docker = DockerService()
    console.print(Panel(Pretty(docker.inspect(container)), title=f"Inspect: {container}"))


@app.command()
def stats(
    container: str = typer.Argument(..., help="Container name or ID"),
):
    """Show one-shot container stats snapshot."""
    console = _common_setup("INFO")
    docker = DockerService()
    console.print(Panel(Pretty(docker.container_stats(container)), title=f"Stats: {container}"))


def _require_ops_enabled(read_only: bool):
    if read_only:
        raise typer.BadParameter("Read-only mode is enabled. Re-run with --read-only=false to perform actions.")


@app.command()
def networks():
    """List Docker networks."""
    console = _common_setup("INFO")
    docker = DockerService()
    ns = NetworkService(docker).list_networks()
    tbl = Table(title="Networks", show_lines=False)
    tbl.add_column("Name")
    tbl.add_column("Driver")
    tbl.add_column("Scope")
    tbl.add_column("Internal")
    tbl.add_column("Attachable")
    tbl.add_column("Containers", justify="right")
    for n in ns:
        tbl.add_row(n.name, n.driver, n.scope, str(n.internal), str(n.attachable), str(n.containers))
    console.print(tbl)


@app.command()
def network_create(
    name: str = typer.Argument(...),
    driver: str = typer.Option("bridge"),
    internal: bool = typer.Option(False),
    attachable: bool = typer.Option(True),
    read_only: bool = typer.Option(True, help="Safety default: actions disabled unless set false"),
):
    """Create a Docker network."""
    _common_setup("INFO")
    _require_ops_enabled(read_only)
    docker = DockerService()
    NetworkService(docker).create(name=name, driver=driver, internal=internal, attachable=attachable)


@app.command()
def network_rm(
    name: str = typer.Argument(...),
    force: bool = typer.Option(False),
    read_only: bool = typer.Option(True, help="Safety default: actions disabled unless set false"),
):
    """Remove a Docker network."""
    _common_setup("INFO")
    _require_ops_enabled(read_only)
    docker = DockerService()
    NetworkService(docker).remove(name, force=force)


@app.command()
def incident_export(
    out: Path = typer.Option(Path.cwd() / "dockermgr_incident.zip"),
    minutes: int = typer.Option(30),
    include_inspects: bool = typer.Option(False),
    disk_path: str = typer.Option("/", help="Disk path to report usage for"),
    no_gpu: bool = typer.Option(False),
):
    """Export an incident bundle (zip)."""
    console = _common_setup("INFO")
    docker = DockerService()
    metrics = HostMetricsProvider(disk_path=disk_path, include_gpu=not no_gpu)
    cfg = ConfigManager()
    p = IncidentExporter(docker, metrics, cfg).export_zip(out, minutes=minutes, include_inspects=include_inspects)
    console.print(f"[green]Created:[/green] {p}")
