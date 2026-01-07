from __future__ import annotations

import logging
from typing import Dict, List, Optional, Iterable

from typing import TYPE_CHECKING

try:
    import docker  # type: ignore
    from docker.errors import DockerException, NotFound  # type: ignore
except ModuleNotFoundError:  # pragma: no cover
    docker = None  # type: ignore
    DockerException = Exception  # type: ignore
    NotFound = Exception  # type: ignore

if TYPE_CHECKING:  # pragma: no cover
    import docker as _docker

from .models import ContainerSummary, ImageSummary, PortMapping, ComposeProjectRef

log = logging.getLogger(__name__)

LABEL_PROJECT = "com.docker.compose.project"
LABEL_SERVICE = "com.docker.compose.service"
LABEL_WORKDIR = "com.docker.compose.project.working_dir"
LABEL_CONFIG_FILES = "com.docker.compose.project.config_files"
LABEL_ENV_FILE = "com.docker.compose.project.environment_file"


def _iso(ts: str) -> str:
    return (ts or "").replace("T", " ").replace("Z", "")


class DockerService:
    def __init__(self, timeout_s: int = 5):
        self._timeout_s = timeout_s
        self._client = docker.from_env(timeout=timeout_s)

    @property
    def client(self):
        return self._client

    def ping(self) -> bool:
        try:
            self._client.ping()
            return True
        except DockerException as e:
            log.error("Docker ping failed: %s", e)
            return False

    def list_containers(self, all: bool = True) -> List[ContainerSummary]:
        containers = self._client.containers.list(all=all)
        out: List[ContainerSummary] = []
        for c in containers:
            try:
                attrs = c.attrs
                name = (c.name or "").lstrip("/")
                image = getattr(c.image, "tags", None) or [getattr(c.image, "short_id", "")]
                status = getattr(c, "status", "unknown")
                state = (attrs.get("State", {}) or {}).get("Status", status)
                created = attrs.get("Created", "")
                ports = self._extract_ports(attrs)

                state_obj = attrs.get("State", {}) or {}
                health = (state_obj.get("Health") or {}).get("Status", "N/A")
                restart_count = int(state_obj.get("RestartCount", 0) or 0)

                labels = (attrs.get("Config", {}) or {}).get("Labels", {}) or {}
                compose_project = labels.get(LABEL_PROJECT)
                compose_service = labels.get(LABEL_SERVICE)

                out.append(
                    ContainerSummary(
                        id=c.short_id,
                        name=name,
                        image=image[0] if image else "",
                        status=status,
                        state=state,
                        created=_iso(created)[:19],
                        ports=ports,
                        health=str(health),
                        restart_count=restart_count,
                        compose_project=compose_project,
                        compose_service=compose_service,
                    )
                )
            except Exception as e:
                log.warning("Failed to summarise container %s: %s", getattr(c, "short_id", "?"), e)

        out.sort(key=lambda x: (0 if x.state == "running" else 1, x.name.lower()))
        return out

    def get_container(self, name_or_id: str):
        try:
            return self._client.containers.get(name_or_id)
        except NotFound:
            raise
        except DockerException as e:
            log.error("Docker get failed: %s", e)
            raise

    def start(self, name_or_id: str) -> None:
        c = self.get_container(name_or_id)
        log.info("Starting container: %s", c.name)
        c.start()

    def stop(self, name_or_id: str, timeout_s: int = 10) -> None:
        c = self.get_container(name_or_id)
        log.info("Stopping container: %s", c.name)
        c.stop(timeout=timeout_s)

    def restart(self, name_or_id: str, timeout_s: int = 10) -> None:
        c = self.get_container(name_or_id)
        log.info("Restarting container: %s", c.name)
        c.restart(timeout=timeout_s)

    def logs(self, name_or_id: str, tail: int = 200) -> str:
        c = self.get_container(name_or_id)
        data = c.logs(tail=tail)
        try:
            return data.decode("utf-8", errors="replace")
        except Exception:
            return str(data)

    def inspect(self, name_or_id: str) -> dict:
        c = self.get_container(name_or_id)
        return c.attrs

    def container_stats(self, name_or_id: str) -> dict:
        c = self.get_container(name_or_id)
        return c.stats(stream=False)

    def list_images(self) -> List[ImageSummary]:
        imgs = self._client.images.list()
        out: List[ImageSummary] = []
        for img in imgs:
            attrs = getattr(img, "attrs", {}) or {}
            created = attrs.get("Created", "")
            size = float(attrs.get("Size", 0.0))
            tags = list(getattr(img, "tags", []) or [])
            out.append(
                ImageSummary(
                    id=img.short_id,
                    tags=tags if tags else ["<none>"],
                    size_mb=round(size / (1024 * 1024), 1),
                    created=_iso(created)[:19],
                )
            )
        out.sort(key=lambda x: (-x.size_mb, x.tags[0]))
        return out

    def discover_compose_projects(self, containers: Optional[List[ContainerSummary]] = None) -> Dict[str, ComposeProjectRef]:
        """Discover compose projects from container labels (best effort).

        Compose v2 typically sets:
          - com.docker.compose.project
          - com.docker.compose.project.working_dir
          - com.docker.compose.project.config_files (comma-separated)
        """
        if containers is None:
            containers = self.list_containers(all=True)

        projects: Dict[str, ComposeProjectRef] = {}
        for c in containers:
            if not c.compose_project:
                continue
            try:
                attrs = self.inspect(c.name)
                labels = (attrs.get("Config", {}) or {}).get("Labels", {}) or {}
                name = labels.get(LABEL_PROJECT)
                if not name:
                    continue

                workdir = labels.get(LABEL_WORKDIR)
                config_files_raw = labels.get(LABEL_CONFIG_FILES) or ""
                config_files = [p.strip() for p in config_files_raw.split(",") if p.strip()]
                env_file = labels.get(LABEL_ENV_FILE)
                # Merge: prefer first-seen with richer info
                prev = projects.get(name)
                if prev is None or ((not prev.working_dir) and workdir) or ((not prev.config_files) and config_files):
                    projects[name] = ComposeProjectRef(
                        name=name,
                        working_dir=workdir,
                        config_files=config_files,
                        environment_file=env_file,
                    )
            except Exception:
                continue
        return projects

    @staticmethod
    def _extract_ports(attrs: dict) -> List[PortMapping]:
        ports_section = (attrs.get("NetworkSettings", {}) or {}).get("Ports", {}) or {}
        mappings: List[PortMapping] = []
        for container_port, host_list in ports_section.items():
            if host_list is None:
                mappings.append(PortMapping(container_port=container_port, host_ip=None, host_port=None))
                continue
            for h in host_list:
                mappings.append(
                    PortMapping(
                        container_port=container_port,
                        host_ip=h.get("HostIp"),
                        host_port=h.get("HostPort"),
                    )
                )
        return mappings
