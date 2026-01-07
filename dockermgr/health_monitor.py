from __future__ import annotations

import json
import logging
import time
from collections import defaultdict, deque
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Deque, Dict, List, Optional, Tuple

from .config import ConfigManager
from .docker_service import DockerService
from .models import ContainerSummary

log = logging.getLogger(__name__)


@dataclass(frozen=True)
class HealthSample:
    ts: str
    container: str
    state: str
    health: str
    restart_count: int


class HealthMonitor:
    """Lightweight in-process health trend tracker.

    - Maintains in-memory history for the current run.
    - Writes JSONL to disk for later analysis (optional).
    """

    def __init__(self, docker: DockerService, max_samples_per_container: int = 120):
        self.docker = docker
        self.max_samples_per_container = max_samples_per_container
        self._hist: Dict[str, Deque[HealthSample]] = defaultdict(lambda: deque(maxlen=max_samples_per_container))
        self._cfg = ConfigManager()
        self._log_path = self._cfg.health_log()

    def sample_once(self, containers: Optional[List[ContainerSummary]] = None) -> None:
        if containers is None:
            containers = self.docker.list_containers(all=True)

        ts = datetime.now(tz=timezone.utc).astimezone().strftime("%Y-%m-%d %H:%M:%S%z")
        for c in containers:
            s = HealthSample(
                ts=ts,
                container=c.name,
                state=c.state,
                health=c.health or "N/A",
                restart_count=int(c.restart_count or 0),
            )
            self._hist[c.name].append(s)
            self._append_to_disk(s)

    def history(self, container_name: str) -> List[HealthSample]:
        return list(self._hist.get(container_name, deque()))

    def _append_to_disk(self, s: HealthSample) -> None:
        rec = {
            "ts": s.ts,
            "container": s.container,
            "state": s.state,
            "health": s.health,
            "restart_count": s.restart_count,
        }
        with self._log_path.open("a", encoding="utf-8") as f:
            f.write(json.dumps(rec) + "\n")
