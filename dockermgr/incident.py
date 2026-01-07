from __future__ import annotations

import json
import logging
import zipfile
from dataclasses import asdict
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Optional, List, Dict

from .docker_service import DockerService
from .config import ConfigManager
from .utils.system_metrics import HostMetricsProvider

log = logging.getLogger(__name__)


def _parse_ts(line: str) -> Optional[datetime]:
    try:
        obj = json.loads(line)
        ts = obj.get("ts")
        if not ts:
            return None
        return datetime.strptime(ts, "%Y-%m-%d %H:%M:%S%z")
    except Exception:
        return None


class IncidentExporter:
    def __init__(self, docker: DockerService, metrics: HostMetricsProvider, cfg: Optional[ConfigManager] = None):
        self.docker = docker
        self.metrics = metrics
        self.cfg = cfg or ConfigManager()

    def export_zip(self, out_path: Path, minutes: int = 30, include_inspects: bool = False) -> Path:
        out_path.parent.mkdir(parents=True, exist_ok=True)

        now = datetime.now(tz=timezone.utc).astimezone()
        since = now - timedelta(minutes=minutes)

        host = self.metrics.snapshot()
        containers = self.docker.list_containers(all=True)
        images = self.docker.list_images()
        projects = self.docker.discover_compose_projects(containers)

        snapshot = {
            "generated_at": now.strftime("%Y-%m-%d %H:%M:%S%z"),
            "window_minutes": minutes,
            "host": asdict(host),
            "containers": [asdict(c) for c in containers],
            "images_top": [asdict(i) for i in images[:25]],
            "compose_projects_discovered": {k: asdict(v) for k, v in projects.items()},
        }

        events_path = self.cfg.events_log()
        health_path = self.cfg.health_log()

        def filter_jsonl(path: Path) -> str:
            if not path.exists():
                return ""
            out_lines: List[str] = []
            for line in path.read_text(encoding="utf-8").splitlines():
                dt = _parse_ts(line)
                if dt and dt >= since:
                    out_lines.append(line)
            return "\n".join(out_lines) + ("\n" if out_lines else "")

        events_recent = filter_jsonl(events_path)
        health_recent = filter_jsonl(health_path)

        inspects: Dict[str, dict] = {}
        if include_inspects:
            for c in containers:
                try:
                    inspects[c.name] = self.docker.inspect(c.name)
                except Exception:
                    continue

        with zipfile.ZipFile(out_path, "w", compression=zipfile.ZIP_DEFLATED) as z:
            z.writestr("snapshot.json", json.dumps(snapshot, indent=2))
            if events_recent:
                z.writestr("docker_events_recent.jsonl", events_recent)
            if health_recent:
                z.writestr("health_samples_recent.jsonl", health_recent)
            if inspects:
                z.writestr("container_inspects.json", json.dumps(inspects, indent=2))

            cfg_path = self.cfg.path
            if cfg_path.exists():
                z.write(cfg_path, arcname="config.yaml")
            overrides_dir = self.cfg.overrides_dir()
            for p in overrides_dir.glob("*.override.yaml"):
                z.write(p, arcname=f"overrides/{p.name}")

        return out_path
