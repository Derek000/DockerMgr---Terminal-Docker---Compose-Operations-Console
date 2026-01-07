from __future__ import annotations

import logging
import time
from pathlib import Path
from typing import Optional, List

from rich.console import Console
from rich.live import Live
from rich.panel import Panel
from rich.pretty import Pretty
from rich.table import Table
from rich.prompt import Prompt, IntPrompt

from ..docker_service import DockerService
from ..compose_service import ComposeService
from ..config import ConfigManager
from ..utils.system_metrics import HostMetricsProvider
from ..event_monitor import DockerEventMonitor
from ..health_monitor import HealthMonitor
from ..network_service import NetworkService
from ..incident import IncidentExporter
from ..reconfigure import load_override, save_override, ProjectOverride, ServiceOverride, yaml_dump_override
from ..utils.diff import unified_text_diff
from ..utils.port_guardrails import parse_compose_ports, detect_port_conflicts
from ..policy import normalise_ports, allow_external_network_creation
from ..impact import impact_summary

from .render import render_dashboard

log = logging.getLogger(__name__)


class DashboardRunner:
    def __init__(self, docker: DockerService, metrics: HostMetricsProvider, console: Optional[Console] = None):
        self.docker = docker
        self.metrics = metrics
        self.console = console or Console()
        self.events = DockerEventMonitor(docker)
        self.health = HealthMonitor(docker)

    def run(self, refresh_s: float = 1.0, read_only: bool = True) -> None:
        if not self.docker.ping():
            raise RuntimeError("Docker daemon not reachable. Check docker service and permissions.")

        self.events.start()
        with Live(console=self.console, refresh_per_second=max(1, int(1 / max(refresh_s, 0.1)))) as live:
            while True:
                host = self.metrics.snapshot()
                containers = self.docker.list_containers(all=True)
                self.health.sample_once(containers)
                images = self.docker.list_images()
                live.update(render_dashboard(host, containers, images, events=self.events.snapshot(), read_only=read_only))
                time.sleep(refresh_s)


class MenuApp:
    def __init__(self, docker: DockerService, metrics: HostMetricsProvider, console: Optional[Console] = None):
        self.docker = docker
        self.metrics = metrics
        self.console = console or Console()
        self.compose = ComposeService()
        self.cfg = ConfigManager()
        self.events = DockerEventMonitor(docker)
        self.health = HealthMonitor(docker)
        self.networks = NetworkService(docker)

    def run(self, read_only: bool = True) -> None:
        if not self.docker.ping():
            self.console.print("[red]Docker daemon not reachable.[/red] Check docker service and permissions.")
            return

        self.events.start()

        while True:
            self._render_once(read_only=read_only)
            choice = Prompt.ask(
                "Choose",
                choices=["refresh", "projects", "containers", "networks", "images", "ports", "health", "incident", "quit"],
                default="projects",
            )
            if choice == "quit":
                return
            if choice == "refresh":
                continue
            if choice == "projects":
                self._projects_menu(read_only=read_only)
            elif choice == "containers":
                self._containers_menu(read_only=read_only)
            elif choice == "networks":
                self._networks_menu(read_only=read_only)
            elif choice == "images":
                self._images_menu()
            elif choice == "ports":
                self._ports_view()
            elif choice == "health":
                self._health_view()
            elif choice == "incident":
                self._incident_menu()

    def _render_once(self, read_only: bool) -> None:
        self.console.clear()
        host = self.metrics.snapshot()
        containers = self.docker.list_containers(all=True)
        self.health.sample_once(containers)
        images = self.docker.list_images()
        layout = render_dashboard(host, containers, images, events=self.events.snapshot(), read_only=read_only)
        self.console.print(layout)

    # ---------- Compose projects ----------

    def _projects_menu(self, read_only: bool) -> None:
        containers = self.docker.list_containers(all=True)
        discovered = self.docker.discover_compose_projects(containers)
        cfg = self.cfg.load()

        projects = dict(discovered)
        for name, ref in cfg.projects.items():
            projects[name] = ref

        if not projects:
            self.console.print("[yellow]No Docker Compose projects discovered.[/yellow]")
            self.console.print(f"Tip: projects are discovered from compose labels. If missing, register one in config:\n  {self.cfg.path}")
            Prompt.ask("Press Enter to return", default="")
            return

        tbl = Table(title="Compose projects", show_lines=False)
        tbl.add_column("#", justify="right")
        tbl.add_column("Project")
        tbl.add_column("Working dir", overflow="fold")
        tbl.add_column("Config files", overflow="fold")
        items = list(sorted(projects.items(), key=lambda x: x[0].lower()))
        for idx, (name, ref) in enumerate(items, start=1):
            tbl.add_row(str(idx), name, ref.working_dir or "-", ", ".join(ref.config_files) or "-")
        self.console.print(tbl)

        sel = IntPrompt.ask("Select project number (0 to return)", default=0)
        if sel <= 0 or sel > len(items):
            return
        _, ref = items[sel - 1]
        self._project_detail(ref, read_only=read_only)

    def _project_detail(self, project_ref, read_only: bool) -> None:
        self.console.clear()
        self.console.print(Panel(f"[bold]{project_ref.name}[/bold]", title="Compose project"))

        containers = [c for c in self.docker.list_containers(all=True) if c.compose_project == project_ref.name]
        tbl = Table(title="Project containers", show_lines=False)
        tbl.add_column("Service")
        tbl.add_column("Container")
        tbl.add_column("State")
        tbl.add_column("Health")
        tbl.add_column("Ports", overflow="fold")
        for c in containers:
            ports = ", ".join([f"{cp}->{hp}" for (cp, hp) in [p.as_tuple() for p in c.ports][:4]]) or "-"
            tbl.add_row(c.compose_service or "-", c.name, c.state, c.health, ports)
        self.console.print(tbl)

        action = Prompt.ask(
            "Project action",
            choices=["up", "down", "restart", "pull", "reconfigure", "validate", "register", "back"],
            default="reconfigure",
        )
        if action == "back":
            return

        if action == "register":
            self._register_project(project_ref)
            return

        if read_only and action in {"up", "down", "restart", "pull", "reconfigure"}:
            self.console.print("[red]Read-only mode: project actions are disabled.[/red]")
            Prompt.ask("Press Enter to return", default="")
            return

        if not project_ref.working_dir or not project_ref.config_files:
            self.console.print("[yellow]Project metadata incomplete.[/yellow]")
            self.console.print("To manage this project reliably, register working_dir and config_files.")
            self._register_project(project_ref)
            return

        override_file = self.cfg.override_file(project_ref.name)
        extra_files = [str(override_file)] if override_file.exists() else None

        if action == "reconfigure":
            self._reconfigure_project(project_ref)
            return

        try:
            if action == "validate":
                res = self.compose.config(project_ref, extra_files=extra_files)
            elif action == "pull":
                res = self.compose.pull(project_ref, extra_files=extra_files)
            elif action == "up":
                res = self.compose.up(project_ref, extra_files=extra_files, pull=False, force_recreate=False, compatibility=True)
            elif action == "down":
                res = self.compose.down(project_ref, extra_files=extra_files)
            elif action == "restart":
                res = self.compose.restart(project_ref, extra_files=extra_files)
            else:
                return

            self.console.print(Panel(res.stdout or "(no stdout)", title=f"compose {action} stdout"))
            if res.stderr:
                self.console.print(Panel(res.stderr, title=f"compose {action} stderr"))
            if res.rc != 0:
                self.console.print(f"[red]Command exited with rc={res.rc}[/red]")
        except Exception as e:
            self.console.print(f"[red]Compose action failed:[/red] {e}")

        Prompt.ask("Press Enter to return", default="")

    def _register_project(self, project_ref) -> None:
        cfg = self.cfg.load()
        self.console.print(Panel("Register/override project metadata in dockermgr config", title="Register project"))
        workdir = Prompt.ask("Working directory", default=project_ref.working_dir or "")
        files = Prompt.ask("Compose config files (comma-separated)", default=",".join(project_ref.config_files or []))
        envf = Prompt.ask("Environment file (optional)", default=project_ref.environment_file or "")
        cfg.projects[project_ref.name] = type(project_ref)(
            name=project_ref.name,
            working_dir=workdir or None,
            config_files=[f.strip() for f in files.split(",") if f.strip()],
            environment_file=envf or None,
        )
        self.cfg.save(cfg)
        self.console.print(f"[green]Saved:[/green] {self.cfg.path}")
        Prompt.ask("Press Enter to return", default="")

    # ---------- Reconfigure wizard ----------

    def _reconfigure_project(self, project_ref) -> None:
        override_path = self.cfg.override_file(project_ref.name)
        current = load_override(override_path)
        before_text = yaml_dump_override(current)

        containers = [c for c in self.docker.list_containers(all=True) if c.compose_project == project_ref.name]
        services = sorted({c.compose_service for c in containers if c.compose_service}, key=lambda x: x.lower())

        if not services:
            self.console.print("[yellow]No services discovered for this project (compose labels missing?).[/yellow]")
            Prompt.ask("Press Enter to return", default="")
            return

        tbl = Table(title=f"Reconfigure: {project_ref.name}", show_lines=False)
        tbl.add_column("#", justify="right")
        tbl.add_column("Service")
        tbl.add_column("CPU", justify="right")
        tbl.add_column("Memory", justify="right")
        tbl.add_column("Env", justify="right")
        tbl.add_column("EnvFile", overflow="fold")
        tbl.add_column("Ports", justify="right")
        tbl.add_column("Secrets", justify="right")
        for i, svc in enumerate(services, start=1):
            so = current.services.get(svc) or ServiceOverride()
            tbl.add_row(
                str(i),
                svc,
                "-" if so.cpus is None else str(so.cpus),
                "-" if so.memory is None else str(so.memory),
                str(len(so.environment)),
                so.env_file or "-",
                str(len(so.ports)),
                str(len(so.secrets)),
            )
        self.console.print(tbl)

        choice = Prompt.ask(
            "Reconfigure action",
            choices=["edit-service", "networks", "secrets", "preview-diff", "apply", "clear", "back"],
            default="edit-service",
        )
        if choice == "back":
            return

        if choice == "clear":
            if override_path.exists():
                override_path.unlink()
            self.console.print("[green]Cleared override file.[/green]")
            Prompt.ask("Press Enter to return", default="")
            return

        if choice == "networks":
            self._edit_networks(current)
            save_override(override_path, current)
            self.console.print(f"[green]Saved override:[/green] {override_path}")
            Prompt.ask("Press Enter to return", default="")
            return

        if choice == "secrets":
            self._edit_project_secrets(current)
            save_override(override_path, current)
            self.console.print(f"[green]Saved override:[/green] {override_path}")
            Prompt.ask("Press Enter to return", default="")
            return

        if choice == "edit-service":
            sel = IntPrompt.ask("Select service number", default=1)
            if sel < 1 or sel > len(services):
                return
            svc = services[sel - 1]
            so = current.services.get(svc) or ServiceOverride()
            self._edit_service(svc, so, project_override=current)
            current.services[svc] = so
            save_override(override_path, current)
            self.console.print(f"[green]Saved override:[/green] {override_path}")
            Prompt.ask("Press Enter to return", default="")
            return

        if choice == "preview-diff":
            after_text = yaml_dump_override(current)
            diff = unified_text_diff(before_text, after_text, fromfile="override.before.yaml", tofile="override.after.yaml")
            self.console.print(Panel(diff or "(no changes)", title="Preview diff"))
            Prompt.ask("Press Enter to return", default="")
            return

        if choice == "apply":
    # 1) Show override diff for operator confidence
    after_text = yaml_dump_override(current)
    diff = unified_text_diff(before_text, after_text, fromfile="override.before.yaml", tofile="override.after.yaml")
    if diff:
        self.console.print(Panel(diff, title="Diff to be applied"))

    # 2) Apply policy defaults (safe-by-default) and produce findings
    cfg = self.cfg.load()
    policy = cfg.policies
    policy_findings = []

    apply_policy = Prompt.ask("Apply policy defaults to ports now? (yes/no)", choices=["yes", "no"], default="yes")
    if apply_policy == "yes":
        for svc_name, so in (current.services or {}).items():
            if not so.ports:
                continue
            norm, findings = normalise_ports(list(so.ports), policy)
            # Update in-memory override so the diff/compose config reflects the actual outcome
            so.ports = norm
            policy_findings.extend(findings)

    # Display policy findings (warnings/errors)
    if policy_findings:
        ft = Table(title="Policy findings", show_lines=False)
        ft.add_column("Level")
        ft.add_column("Code")
        ft.add_column("Port", overflow="fold")
        ft.add_column("Message", overflow="fold")
        for f in policy_findings:
            ft.add_row(f.level, f.code, f.port_line or "-", f.message)
        self.console.print(ft)

        errors = [f for f in policy_findings if f.level == "error"]
        if errors:
            self.console.print("[red]Policy errors detected. Blocking apply by default.[/red]")
            proceed = Prompt.ask("Override and proceed anyway? (yes/no)", choices=["yes", "no"], default="no")
            if proceed != "yes":
                return

    # 3) Guardrails: port conflicts against current host and Docker bindings
    conflicts = self._check_port_conflicts(current)
    if conflicts:
        ct = Table(title="Port conflicts detected", show_lines=False)
        ct.add_column("HostPort")
        ct.add_column("Proto")
        ct.add_column("Reason")
        ct.add_column("Detail", overflow="fold")
        for c in conflicts:
            ct.add_row(str(c.host_port), c.proto, c.reason, c.detail)
        self.console.print(ct)
        proceed = Prompt.ask("Proceed anyway? (yes/no)", choices=["yes", "no"], default="no")
        if proceed != "yes":
            return

    # 4) External networks: detect missing and optionally create (policy constrained)
    missing_ext = self._missing_external_networks(current)
    if missing_ext:
        self.console.print(Panel("\n".join(missing_ext), title="Missing external networks"))
    create_ext = False
    if missing_ext:
        create_ext = Prompt.ask("Create missing external networks now? (yes/no)", choices=["yes", "no"], default="no") == "yes"

    # Always save override before running dry-run/config/apply so the operator can review it.
    save_override(override_path, current)
    self.console.print(f"[green]Saved override:[/green] {override_path}")

    # 5) Dry-run support: generate effective compose config and stop
    dry_run = Prompt.ask("Dry-run only? (yes/no)", choices=["yes", "no"], default="yes") == "yes"
    if dry_run:
        try:
            res = self.compose.config(project_ref, extra_files=[str(override_path)])
            self.console.print(Panel(res.stdout or "(no stdout)", title="compose config (dry-run) stdout"))
            if res.stderr:
                self.console.print(Panel(res.stderr, title="compose config (dry-run) stderr"))
            if res.rc != 0:
                self.console.print(f"[red]Dry-run exited with rc={res.rc}[/red]")
        except Exception as e:
            self.console.print(f"[red]Dry-run failed:[/red] {e}")
        Prompt.ask("Press Enter to return", default="")
        return

    # 6) Apply: optional external network creation (policy allowlist), then compose up
    if create_ext and missing_ext:
        for n in missing_ext:
            if not allow_external_network_creation(n, policy):
                self.console.print(f"[yellow]Policy blocked creation of external network:[/yellow] {n}")
                continue
            try:
                self.networks.create(n, driver="bridge", internal=False, attachable=True)
            except Exception as e:
                self.console.print(f"[red]Failed to create network {n}:[/red] {e}")

    do_recreate = Prompt.ask("Force recreate? (yes/no)", choices=["yes", "no"], default="no") == "yes"
    try:
        res = self.compose.up(
            project_ref,
            extra_files=[str(override_path)],
            pull=False,
            force_recreate=do_recreate,
            compatibility=True,
        )
        self.console.print(Panel(res.stdout or "(no stdout)", title="compose up stdout"))
        if res.stderr:
            self.console.print(Panel(res.stderr, title="compose up stderr"))
        if res.rc != 0:
            self.console.print(f"[red]Apply failed rc={res.rc}[/red]")
    except Exception as e:
        self.console.print(f"[red]Apply failed:[/red] {e}")
    Prompt.ask("Press Enter to return", default="")
    return

            return

    def _check_port_conflicts(self, po: ProjectOverride):
        docker_bindings = set()
        for c in self.docker.list_containers(all=True):
            for pm in c.ports:
                proto = "tcp"
                if "/" in pm.container_port:
                    proto = pm.container_port.split("/", 1)[1].lower()
                if pm.host_port and pm.host_port.isdigit():
                    docker_bindings.add((int(pm.host_port), proto))

        requested = []
        for so in (po.services or {}).values():
            requested += parse_compose_ports(so.ports or [])
        return detect_port_conflicts(requested=requested, docker_bindings=docker_bindings)

    def _missing_external_networks(self, po: ProjectOverride) -> List[str]:
        missing: List[str] = []
        defined = po.networks or {}
        legacy = po.networks_external or {}

        existing = {n.name for n in self.networks.list_networks()}

        for name, spec in defined.items():
            if isinstance(spec, dict) and spec.get("external") is True and name not in existing:
                missing.append(name)

        for name, is_ext in legacy.items():
            if is_ext and name not in existing and name not in missing:
                missing.append(name)

        return missing

    def _edit_service(self, svc: str, so: ServiceOverride, project_override: ProjectOverride) -> None:
        self.console.clear()
        self.console.print(Panel(f"[bold]{svc}[/bold]", title="Edit service override"))

        cpu_raw = Prompt.ask("CPU limit (e.g., 0.5) blank to keep", default="" if so.cpus is None else str(so.cpus))
        mem_raw = Prompt.ask("Memory limit (e.g., 512M or 2G) blank to keep", default="" if so.memory is None else str(so.memory))

        if cpu_raw.strip():
            try:
                so.cpus = float(cpu_raw)
            except ValueError:
                pass
        if mem_raw.strip():
            so.memory = mem_raw.strip()

        env_file_action = Prompt.ask("Env file", choices=["set", "clear", "skip"], default="skip")
        if env_file_action == "set":
            so.env_file = Prompt.ask("Path to env file", default=so.env_file or "")
        elif env_file_action == "clear":
            so.env_file = None

        env_action = Prompt.ask("Env overrides", choices=["edit", "skip"], default="skip")
        if env_action == "edit":
            self.console.print("Enter KEY=VALUE lines. Blank line to finish.")
            env = dict(so.environment or {})
            while True:
                line = Prompt.ask("env", default="")
                if not line.strip():
                    break
                if "=" not in line:
                    continue
                k, v = line.split("=", 1)
                env[k.strip()] = v.strip()
            so.environment = env

        ports_action = Prompt.ask("Ports", choices=["edit", "skip"], default="skip")
        if ports_action == "edit":
            self.console.print("Enter compose port lines like 8080:80 or 127.0.0.1:8080:80. Blank line to finish.")
            ports: List[str] = []
            while True:
                line = Prompt.ask("port", default="")
                if not line.strip():
                    break
                ports.append(line.strip())
            so.ports = ports

        nets_action = Prompt.ask("Networks", choices=["edit", "skip"], default="skip")
        if nets_action == "edit":
            self.console.print("Enter network names. Blank line to finish.")
            nets: List[str] = []
            while True:
                line = Prompt.ask("network", default="")
                if not line.strip():
                    break
                nets.append(line.strip())
            so.networks = nets

        sec_action = Prompt.ask("Secrets", choices=["attach", "detach", "skip"], default="skip")
        if sec_action != "skip":
            self.console.print("Project secrets available: " + (", ".join(sorted((project_override.secrets or {}).keys())) or "(none)"))
            name = Prompt.ask("Secret name", default="")
            if name.strip():
                if sec_action == "attach":
                    if name not in so.secrets:
                        so.secrets.append(name)
                elif sec_action == "detach":
                    so.secrets = [s for s in so.secrets if s != name]

    def _edit_networks(self, po: ProjectOverride) -> None:
        self.console.clear()
        self.console.print(Panel("Project networks (override)", title="Networks"))
        self.console.print("Define networks here. Compose will create non-external networks on `up`.")
        nets = dict(po.networks or {})

        while True:
            action = Prompt.ask("Networks action", choices=["add", "remove", "set-external", "set-internal", "done"], default="done")
            if action == "done":
                break
            if action == "add":
                name = Prompt.ask("Network name", default="")
                if not name.strip():
                    continue
                driver = Prompt.ask("Driver", default="bridge")
                internal = Prompt.ask("Internal? (yes/no)", choices=["yes", "no"], default="no") == "yes"
                attachable = Prompt.ask("Attachable? (yes/no)", choices=["yes", "no"], default="yes") == "yes"
                nets[name.strip()] = {"driver": driver, "internal": internal, "attachable": attachable}
            if action == "remove":
                name = Prompt.ask("Network name to remove from override", default="")
                if name.strip() in nets:
                    nets.pop(name.strip(), None)
            if action == "set-external":
                name = Prompt.ask("Network name", default="")
                if not name.strip():
                    continue
                ext = Prompt.ask("External? (yes/no)", choices=["yes", "no"], default="yes") == "yes"
                if ext:
                    nets[name.strip()] = {"external": True}
                else:
                    nets[name.strip()] = {"driver": "bridge", "internal": False, "attachable": True}
            if action == "set-internal":
                name = Prompt.ask("Network name", default="")
                if not name.strip():
                    continue
                internal = Prompt.ask("Internal? (yes/no)", choices=["yes", "no"], default="no") == "yes"
                spec = dict(nets.get(name.strip(), {}))
                if spec.get("external") is True:
                    self.console.print("[yellow]External networks cannot be marked internal in compose override.[/yellow]")
                    continue
                spec["internal"] = internal
                spec.setdefault("driver", "bridge")
                spec.setdefault("attachable", True)
                nets[name.strip()] = spec

        po.networks = nets

    def _edit_project_secrets(self, po: ProjectOverride) -> None:
        self.console.clear()
        self.console.print(Panel("Project secrets (override)", title="Secrets"))
        self.console.print("Define file-based secrets (mounted as read-only).")
        secrets = dict(po.secrets or {})
        while True:
            action = Prompt.ask("Secrets action", choices=["add-file", "remove", "list", "done"], default="done")
            if action == "done":
                break
            if action == "list":
                tbl = Table(title="Secrets", show_lines=False)
                tbl.add_column("Name")
                tbl.add_column("Type")
                tbl.add_column("Detail", overflow="fold")
                for name, spec in sorted(secrets.items(), key=lambda x: x[0].lower()):
                    if isinstance(spec, dict) and "file" in spec:
                        tbl.add_row(name, "file", spec.get("file"))
                    elif isinstance(spec, dict) and spec.get("external") is True:
                        tbl.add_row(name, "external", "docker secret")
                    else:
                        tbl.add_row(name, "unknown", str(spec))
                self.console.print(tbl)
            if action == "add-file":
                name = Prompt.ask("Secret name", default="")
                if not name.strip():
                    continue
                fpath = Prompt.ask("Path to secret file", default="")
                if not fpath.strip():
                    continue
                secrets[name.strip()] = {"file": fpath.strip()}
            if action == "remove":
                name = Prompt.ask("Secret name to remove", default="")
                if name.strip() in secrets:
                    secrets.pop(name.strip(), None)
        po.secrets = secrets

    # ---------- Networks menu (host-level Docker networks) ----------

    def _networks_menu(self, read_only: bool) -> None:
        self.console.clear()
        nets = self.networks.list_networks()
        tbl = Table(title="Docker networks", show_lines=False)
        tbl.add_column("#", justify="right")
        tbl.add_column("Name")
        tbl.add_column("Driver")
        tbl.add_column("Scope")
        tbl.add_column("Internal")
        tbl.add_column("Attachable")
        tbl.add_column("Containers", justify="right")
        for i, n in enumerate(nets, start=1):
            tbl.add_row(str(i), n.name, n.driver, n.scope, str(n.internal), str(n.attachable), str(n.containers))
        self.console.print(tbl)

        action = Prompt.ask("Network action", choices=["inspect", "create", "remove", "back"], default="inspect")
        if action == "back":
            return
        if action == "inspect":
            sel = IntPrompt.ask("Select network number (0 to return)", default=0)
            if sel <= 0 or sel > len(nets):
                return
            n = nets[sel - 1]
            self.console.print(Panel(Pretty(self.networks.inspect(n.name)), title=f"Inspect network: {n.name}"))
            Prompt.ask("Press Enter to return", default="")
            return

        if read_only:
            self.console.print("[red]Read-only mode: network actions are disabled.[/red]")
            Prompt.ask("Press Enter to return", default="")
            return

        if action == "create":
            name = Prompt.ask("Network name", default="")
            driver = Prompt.ask("Driver", default="bridge")
            internal = Prompt.ask("Internal? (yes/no)", choices=["yes", "no"], default="no") == "yes"
            attachable = Prompt.ask("Attachable? (yes/no)", choices=["yes", "no"], default="yes") == "yes"
            try:
                self.networks.create(name=name.strip(), driver=driver, internal=internal, attachable=attachable)
                self.console.print("[green]Network created.[/green]")
            except Exception as e:
                self.console.print(f"[red]Create failed:[/red] {e}")
            Prompt.ask("Press Enter to return", default="")
            return

        if action == "remove":
            sel = IntPrompt.ask("Select network number to remove (0 to return)", default=0)
            if sel <= 0 or sel > len(nets):
                return
            n = nets[sel - 1]
            try:
                attached = self.networks.connected_containers(n.name)
                if attached:
                    self.console.print(Panel("\n".join(attached), title=f"Attached containers ({len(attached)})"))
                    force = Prompt.ask("Force remove? (yes/no)", choices=["yes", "no"], default="no") == "yes"
                else:
                    force = False
                self.networks.remove(n.name, force=force)
                self.console.print("[green]Network removed.[/green]")
            except Exception as e:
                self.console.print(f"[red]Remove failed:[/red] {e}")
            Prompt.ask("Press Enter to return", default="")
            return

    # ---------- Other views ----------

    def _containers_menu(self, read_only: bool) -> None:
        containers = self.docker.list_containers(all=True)
        if not containers:
            self.console.print("[yellow]No containers found.[/yellow]")
            return

        tbl = Table(title="Containers", show_lines=False)
        tbl.add_column("#", justify="right")
        tbl.add_column("Name")
        tbl.add_column("Project")
        tbl.add_column("Service")
        tbl.add_column("State")
        tbl.add_column("Health")
        tbl.add_column("Ports", overflow="fold")

        for idx, c in enumerate(containers, start=1):
            ports = ", ".join([f"{cp}->{hp}" for (cp, hp) in [p.as_tuple() for p in c.ports][:3]]) or "-"
            tbl.add_row(str(idx), c.name, c.compose_project or "-", c.compose_service or "-", c.state, c.health, ports)

        self.console.print(tbl)
        sel = IntPrompt.ask("Select container number (0 to return)", default=0)
        if sel <= 0 or sel > len(containers):
            return
        c = containers[sel - 1]
        self._container_detail(c.name, read_only=read_only)

    def _container_detail(self, name_or_id: str, read_only: bool) -> None:
        self.console.clear()
        attrs = self.docker.inspect(name_or_id)
        stats = None
        try:
            stats = self.docker.container_stats(name_or_id)
        except Exception as e:
            log.debug("Stats unavailable for %s: %s", name_or_id, e)

        self.console.print(Panel(f"[bold]{name_or_id}[/bold] — Inspection", title="Container"))
        state = (attrs.get("State") or {})
        cfg = (attrs.get("Config") or {})
        net = (attrs.get("NetworkSettings") or {})

        key_tbl = Table(show_header=False)
        key_tbl.add_column("Key")
        key_tbl.add_column("Value", overflow="fold")
        key_tbl.add_row("Image", str(cfg.get("Image")))
        key_tbl.add_row("Status", str(state.get("Status")))
        key_tbl.add_row("Health", str((state.get("Health") or {}).get("Status", "N/A")))
        key_tbl.add_row("StartedAt", str(state.get("StartedAt", ""))[:19].replace("T", " "))
        key_tbl.add_row("RestartCount", str(state.get("RestartCount", 0)))
        key_tbl.add_row("IPAddress", str(net.get("IPAddress", "")))
        self.console.print(Panel(key_tbl, title="Summary"))

        if stats:
            self.console.print(Panel(Pretty(stats), title="Raw stats snapshot"))

        action = Prompt.ask(
            "Action",
            choices=["logs", "inspect-json", "start", "stop", "restart", "back"],
            default="logs",
        )
        if action == "back":
            return
        if action == "logs":
            tail = IntPrompt.ask("Tail lines", default=200)
            self.console.clear()
            self.console.print(Panel(self.docker.logs(name_or_id, tail=tail), title=f"Logs: {name_or_id}"))
            Prompt.ask("Press Enter to return", default="")
            return
        if action == "inspect-json":
            self.console.clear()
            self.console.print(Panel(Pretty(attrs), title=f"Inspect JSON: {name_or_id}"))
            Prompt.ask("Press Enter to return", default="")
            return

        if read_only:
            self.console.print("[red]Read-only mode: operational actions are disabled.[/red]")
            Prompt.ask("Press Enter to return", default="")
            return

        try:
            if action == "start":
                self.docker.start(name_or_id)
            elif action == "stop":
                self.docker.stop(name_or_id)
            elif action == "restart":
                self.docker.restart(name_or_id)
            self.console.print("[green]Done.[/green]")
        except Exception as e:
            self.console.print(f"[red]Action failed:[/red] {e}")
        Prompt.ask("Press Enter to return", default="")

    def _images_menu(self) -> None:
        images = self.docker.list_images()
        tbl = Table(title="Images", show_lines=False)
        tbl.add_column("ID", no_wrap=True)
        tbl.add_column("Tags", overflow="fold")
        tbl.add_column("Size (MB)", justify="right")
        tbl.add_column("Created", no_wrap=True)
        for im in images[:80]:
            tbl.add_row(im.id, ", ".join(im.tags), f"{im.size_mb:.1f}", im.created)
        self.console.print(tbl)
        Prompt.ask("Press Enter to return", default="")

    def _ports_view(self) -> None:
        containers = self.docker.list_containers(all=True)
        tbl = Table(title="Port mappings (container → host)", show_lines=False)
        tbl.add_column("Container", no_wrap=True)
        tbl.add_column("Project", no_wrap=True)
        tbl.add_column("Service", no_wrap=True)
        tbl.add_column("Mapping", overflow="fold")

        for c in containers:
            if not c.ports:
                continue
            mappings = "; ".join([f"{cp} → {hp}" for (cp, hp) in [p.as_tuple() for p in c.ports]])
            tbl.add_row(c.name, c.compose_project or "-", c.compose_service or "-", mappings)
        self.console.print(tbl)
        Prompt.ask("Press Enter to return", default="")

    def _health_view(self) -> None:
        containers = self.docker.list_containers(all=True)
        tbl = Table(title="Health (from Docker inspect)", show_lines=False)
        tbl.add_column("Container")
        tbl.add_column("Project")
        tbl.add_column("State")
        tbl.add_column("Health")
        tbl.add_column("RestartCount", justify="right")

        for c in containers:
            tbl.add_row(c.name, c.compose_project or "-", c.state, c.health, str(c.restart_count))
        self.console.print(tbl)
        Prompt.ask("Press Enter to return", default="")

    # ---------- Incident menu ----------

    def _incident_menu(self) -> None:
        self.console.clear()
        self.console.print(Panel("Export an incident bundle (snapshot + recent events/health + config/overrides)", title="Incident bundle"))
        minutes = IntPrompt.ask("Window minutes", default=30)
        include_inspects = Prompt.ask("Include full container inspect JSON? (yes/no)", choices=["yes", "no"], default="no") == "yes"
        out = Prompt.ask("Output zip path", default=str(Path.cwd() / f"dockermgr_incident_{int(time.time())}.zip"))
        try:
            exporter = IncidentExporter(self.docker, self.metrics, self.cfg)
            p = exporter.export_zip(Path(out), minutes=minutes, include_inspects=include_inspects)
            self.console.print(f"[green]Created:[/green] {p}")
        except Exception as e:
            self.console.print(f"[red]Export failed:[/red] {e}")
        Prompt.ask("Press Enter to return", default="")
