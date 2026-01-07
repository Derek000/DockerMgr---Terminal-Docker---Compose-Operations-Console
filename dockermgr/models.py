from __future__ import annotations

from dataclasses import dataclass
from typing import List, Optional, Tuple, Dict


@dataclass(frozen=True)
class PortMapping:
    container_port: str
    host_ip: Optional[str]
    host_port: Optional[str]

    def as_tuple(self) -> Tuple[str, str]:
        host = f"{self.host_ip or '0.0.0.0'}:{self.host_port or '-'}"
        return (self.container_port, host)


@dataclass(frozen=True)
class ContainerSummary:
    id: str
    name: str
    image: str
    status: str
    state: str
    created: str
    ports: List[PortMapping]
    health: str  # "healthy" | "unhealthy" | "starting" | "N/A"
    restart_count: int
    compose_project: Optional[str] = None
    compose_service: Optional[str] = None


@dataclass(frozen=True)
class ImageSummary:
    id: str
    tags: List[str]
    size_mb: float
    created: str


@dataclass(frozen=True)
class HostMetrics:
    cpu_percent: float
    mem_used_gb: float
    mem_total_gb: float
    mem_percent: float
    disk_used_gb: float
    disk_total_gb: float
    disk_percent: float
    net_sent_mb: float
    net_recv_mb: float
    disk_read_mb: float
    disk_write_mb: float
    gpu_summary: Optional[str] = None


@dataclass(frozen=True)
class ComposeProjectRef:
    name: str
    working_dir: Optional[str]
    config_files: List[str]
    environment_file: Optional[str] = None


@dataclass(frozen=True)
class ProjectSummary:
    name: str
    running: int
    total: int
    unhealthy: int
    restarting: int
