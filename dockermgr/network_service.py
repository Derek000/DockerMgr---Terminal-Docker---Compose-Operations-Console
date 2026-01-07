from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Dict, List, Optional

from .docker_service import DockerService

log = logging.getLogger(__name__)


@dataclass(frozen=True)
class NetworkSummary:
    id: str
    name: str
    driver: str
    scope: str
    internal: bool
    attachable: bool
    containers: int


class NetworkService:
    def __init__(self, docker: DockerService):
        self.docker = docker

    def list_networks(self) -> List[NetworkSummary]:
        nets = self.docker.client.networks.list()
        out: List[NetworkSummary] = []
        for n in nets:
            attrs = getattr(n, "attrs", {}) or {}
            out.append(
                NetworkSummary(
                    id=n.short_id,
                    name=attrs.get("Name", n.name),
                    driver=attrs.get("Driver", ""),
                    scope=attrs.get("Scope", ""),
                    internal=bool(attrs.get("Internal", False)),
                    attachable=bool(attrs.get("Attachable", False)),
                    containers=len(((attrs.get("Containers") or {}) or {})),
                )
            )
        out.sort(key=lambda x: x.name.lower())
        return out

    def inspect(self, name_or_id: str) -> dict:
        n = self.docker.client.networks.get(name_or_id)
        return getattr(n, "attrs", {}) or {}

    def create(
        self,
        name: str,
        driver: str = "bridge",
        internal: bool = False,
        attachable: bool = True,
        labels: Optional[Dict[str, str]] = None,
    ) -> None:
        labels = labels or {}
        log.info("Creating network %s (driver=%s internal=%s attachable=%s)", name, driver, internal, attachable)
        self.docker.client.networks.create(
            name=name,
            driver=driver,
            internal=internal,
            attachable=attachable,
            labels=labels,
        )

    def remove(self, name_or_id: str, force: bool = False) -> None:
        n = self.docker.client.networks.get(name_or_id)
        attrs = getattr(n, "attrs", {}) or {}
        containers = ((attrs.get("Containers") or {}) or {})
        if containers and not force:
            raise RuntimeError(f"Network has attached containers ({len(containers)}). Use force to remove.")
        log.info("Removing network %s", attrs.get("Name", name_or_id))
        n.remove()

    def connected_containers(self, name_or_id: str) -> List[str]:
        attrs = self.inspect(name_or_id)
        containers = ((attrs.get("Containers") or {}) or {})
        names: List[str] = []
        for _, c in containers.items():
            if isinstance(c, dict):
                names.append(c.get("Name", "") or "")
        return [n for n in names if n]
