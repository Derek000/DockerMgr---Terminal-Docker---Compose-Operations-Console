from __future__ import annotations

from typing import List, Sequence, Optional, Dict
from collections import defaultdict

from rich import box
from rich.align import Align
from rich.console import Group
from rich.panel import Panel
from rich.table import Table
from rich.text import Text
from rich.layout import Layout

from ..models import ContainerSummary, HostMetrics, ImageSummary, ProjectSummary
from ..event_monitor import DockerEvent


def _progress_bar(percent: float, width: int = 22) -> Text:
    filled = int((percent / 100.0) * width)
    filled = max(0, min(width, filled))
    bar = "█" * filled + "░" * (width - filled)
    return Text(f"{bar} {percent:.1f}%")


def build_project_summaries(containers: List[ContainerSummary]) -> List[ProjectSummary]:
    by_proj = defaultdict(list)
    for c in containers:
        if c.compose_project:
            by_proj[c.compose_project].append(c)

    summaries: List[ProjectSummary] = []
    for name, cs in sorted(by_proj.items(), key=lambda x: x[0].lower()):
        running = sum(1 for c in cs if c.state == "running")
        unhealthy = sum(1 for c in cs if str(c.health).lower() == "unhealthy")
        restarting = sum(1 for c in cs if int(c.restart_count or 0) > 0)
        summaries.append(ProjectSummary(name=name, running=running, total=len(cs), unhealthy=unhealthy, restarting=restarting))
    return summaries


def render_dashboard(
    host: HostMetrics,
    containers: List[ContainerSummary],
    images: List[ImageSummary],
    events: List[DockerEvent],
    read_only: bool,
) -> Layout:
    layout = Layout(name="root")
    layout.split_column(
        Layout(name="header", size=3),
        Layout(name="body"),
        Layout(name="footer", size=3),
    )
    layout["body"].split_row(Layout(name="left"), Layout(name="right"))

    title = Text("dockermgr — Live Docker + Compose Operations Dashboard", style="bold")
    subtitle = Text("SSH-friendly | Drill-down via `dockermgr menu` | Ctrl+C to exit", style="dim")
    header = Panel(Align.center(Group(title, subtitle)), box=box.ROUNDED)

    # Host metrics
    host_tbl = Table.grid(expand=True)
    host_tbl.add_column(ratio=1)
    host_tbl.add_column(justify="right")
    host_tbl.add_row("CPU", str(_progress_bar(host.cpu_percent)))
    host_tbl.add_row("Memory", f"{host.mem_used_gb:.2f}/{host.mem_total_gb:.2f} GB  {host.mem_percent:.1f}%")
    host_tbl.add_row("Disk (/)", f"{host.disk_used_gb:.2f}/{host.disk_total_gb:.2f} GB  {host.disk_percent:.1f}%")
    host_tbl.add_row("Network (totals)", f"TX {host.net_sent_mb:.1f} MB | RX {host.net_recv_mb:.1f} MB")
    host_tbl.add_row("Disk I/O (totals)", f"R {host.disk_read_mb:.1f} MB | W {host.disk_write_mb:.1f} MB")
    host_tbl.add_row("GPU", host.gpu_summary or "N/A")
    host_panel = Panel(host_tbl, title="Host resources", box=box.ROUNDED)

    # Projects
    proj_tbl = Table(box=box.SIMPLE_HEAVY, expand=True, header_style="bold")
    proj_tbl.add_column("Compose project", overflow="fold")
    proj_tbl.add_column("Running", justify="right")
    proj_tbl.add_column("Total", justify="right")
    proj_tbl.add_column("Unhealthy", justify="right")
    proj_tbl.add_column("Restarting*", justify="right")
    proj_summaries = build_project_summaries(containers)
    for p in proj_summaries[:12]:
        proj_tbl.add_row(p.name, str(p.running), str(p.total), str(p.unhealthy), str(p.restarting))
    proj_panel = Panel(proj_tbl, title="Compose projects", box=box.ROUNDED)

    # Containers summary table (compact)
    cont_tbl = Table(box=box.SIMPLE_HEAVY, expand=True, header_style="bold")
    cont_tbl.add_column("Name", no_wrap=True)
    cont_tbl.add_column("State", no_wrap=True)
    cont_tbl.add_column("Health", no_wrap=True)
    cont_tbl.add_column("Ports", overflow="fold")
    shown = 0
    running = 0
    for c in containers:
        if shown >= 12:
            break
        shown += 1
        if c.state == "running":
            running += 1
        ports = ", ".join([f"{cp}->{hp}" for (cp, hp) in [p.as_tuple() for p in c.ports][:3]])
        if len(c.ports) > 3:
            ports += f" (+{len(c.ports)-3})"
        cont_tbl.add_row(c.name, c.state, c.health, ports or "-")

    cont_panel = Panel(cont_tbl, box=box.ROUNDED, title=f"Containers (showing {shown}/{len(containers)}; running {running})")

    # Images summary
    img_tbl = Table(box=box.SIMPLE_HEAVY, expand=True, header_style="bold")
    img_tbl.add_column("Top images (by size)", overflow="fold")
    img_tbl.add_column("MB", justify="right")
    for im in images[:10]:
        img_tbl.add_row(", ".join(im.tags[:2]) + (" …" if len(im.tags) > 2 else ""), f"{im.size_mb:.1f}")
    img_panel = Panel(img_tbl, box=box.ROUNDED)

    # Recent events
    ev_tbl = Table(box=box.SIMPLE_HEAVY, expand=True, header_style="bold")
    ev_tbl.add_column("Time", no_wrap=True)
    ev_tbl.add_column("Type", no_wrap=True)
    ev_tbl.add_column("Action", no_wrap=True)
    ev_tbl.add_column("Name", overflow="fold")
    for e in (events or [])[:10]:
        ev_tbl.add_row(e.ts[-10:], e.type, e.action, e.name or e.id)
    ev_panel = Panel(ev_tbl, box=box.ROUNDED, title="Recent events")

    layout["header"].update(header)
    layout["left"].split_column(Layout(host_panel, name="host"), Layout(proj_panel, name="projects"), Layout(cont_panel, name="containers"))
    layout["right"].split_column(Layout(img_panel, name="images"), Layout(ev_panel, name="events"))

    ro = "READ-ONLY" if read_only else "OPERATIONS ENABLED"
    footer = Panel(
        Text(
            f"Mode: {ro} | *Restarting is a hint (restart_count>0). Use `dockermgr menu` for project/service actions.",
            style="dim",
        ),
        box=box.ROUNDED,
    )
    layout["footer"].update(footer)
    return layout
