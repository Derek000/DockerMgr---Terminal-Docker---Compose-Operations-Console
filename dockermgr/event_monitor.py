from __future__ import annotations

import json
import logging
import threading
import time
from collections import deque
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Deque, Dict, Optional, List

from docker.errors import DockerException

from .docker_service import DockerService
from .config import ConfigManager

log = logging.getLogger(__name__)


@dataclass(frozen=True)
class DockerEvent:
    ts: str
    type: str
    action: str
    id: str
    name: str


class DockerEventMonitor(threading.Thread):
    """Background Docker event collector.

    Keeps a ring buffer of the most recent events and writes JSONL to disk for audit/troubleshooting.
    """

    def __init__(self, docker: DockerService, max_events: int = 80, poll_sleep: float = 0.1):
        super().__init__(daemon=True)
        self.docker = docker
        self.max_events = max_events
        self.poll_sleep = poll_sleep
        self._stop = threading.Event()
        self._events: Deque[DockerEvent] = deque(maxlen=max_events)
        self._cfg = ConfigManager()
        self._log_path = self._cfg.events_log()

    def stop(self) -> None:
        self._stop.set()

    def snapshot(self) -> List[DockerEvent]:
        return list(self._events)

    def run(self) -> None:
        api = self.docker.client.api
        try:
            stream = api.events(decode=True)
            for ev in stream:
                if self._stop.is_set():
                    break
                try:
                    event = self._normalise(ev)
                    if event:
                        self._events.appendleft(event)
                        self._append_to_disk(event)
                except Exception:
                    continue
                time.sleep(self.poll_sleep)
        except DockerException as e:
            log.debug("Docker events stream ended: %s", e)
        except Exception as e:
            log.debug("Docker events stream error: %s", e)

    def _normalise(self, ev: Dict) -> Optional[DockerEvent]:
        t = ev.get("Type") or ""
        action = ev.get("Action") or ""
        actor = ev.get("Actor") or {}
        attrs = actor.get("Attributes") or {}

        obj_id = (actor.get("ID") or ev.get("id") or ev.get("ID") or "")[:12]
        name = attrs.get("name") or attrs.get("container") or attrs.get("com.docker.compose.service") or ""

        ts = ev.get("time") or int(time.time())
        iso = datetime.fromtimestamp(ts, tz=timezone.utc).astimezone().strftime("%Y-%m-%d %H:%M:%S%z")

        if not t and not action:
            return None

        return DockerEvent(ts=iso, type=str(t), action=str(action), id=str(obj_id), name=str(name))

    def _append_to_disk(self, event: DockerEvent) -> None:
        rec = {"ts": event.ts, "type": event.type, "action": event.action, "id": event.id, "name": event.name}
        with self._log_path.open("a", encoding="utf-8") as f:
            f.write(json.dumps(rec) + "\n")
