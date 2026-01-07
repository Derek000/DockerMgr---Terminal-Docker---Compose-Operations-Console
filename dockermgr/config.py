from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, List, Optional

import yaml

from .models import ComposeProjectRef


def _xdg_config_home() -> Path:
    return Path(os.environ.get("XDG_CONFIG_HOME", Path.home() / ".config"))


def _xdg_state_home() -> Path:
    return Path(os.environ.get("XDG_STATE_HOME", Path.home() / ".local" / "state"))



@dataclass
class PolicyConfig:
    """Operational safety defaults.

    These defaults aim to reduce accidental exposure (e.g., publishing services on 0.0.0.0)
    and reduce blast radius when applying changes.

    All fields can be overridden in ~/.config/dockermgr/config.yaml
    """
    default_bind_ip: str = "127.0.0.1"          # Applied to ports that omit an IP (e.g., 8080:80)
    require_explicit_public: bool = True        # Warn if a port is published without IP and default_bind_ip is empty
    allow_privileged_ports: bool = False        # Ports <1024 require explicit opt-in
    deny_public_bind_all: bool = False          # If True, block 0.0.0.0 binds (operator can override per apply)
    external_network_prefix_allowlist: List[str] = field(default_factory=list)  # Optional allowlist for creating external networks


@dataclass
class AppConfig:
    # Explicit registry for compose projects (fallback when labels don't contain enough info)
    projects: Dict[str, ComposeProjectRef]
    policies: PolicyConfig


class ConfigManager:
    def __init__(self) -> None:
        self.config_dir = _xdg_config_home() / "dockermgr"
        self.state_dir = _xdg_state_home() / "dockermgr"
        self.config_dir.mkdir(parents=True, exist_ok=True)
        self.state_dir.mkdir(parents=True, exist_ok=True)
        self.path = self.config_dir / "config.yaml"

    def load(self) -> AppConfig:
        if not self.path.exists():
            return AppConfig(projects={}, policies=PolicyConfig())
        data = yaml.safe_load(self.path.read_text(encoding="utf-8")) or {}
        ppol = data.get("policies") or {}
        allowlist = list(ppol.get("external_network_prefix_allowlist") or [])
        policies = PolicyConfig(
            default_bind_ip=str(ppol.get("default_bind_ip", "127.0.0.1")),
            require_explicit_public=bool(ppol.get("require_explicit_public", True)),
            allow_privileged_ports=bool(ppol.get("allow_privileged_ports", False)),
            deny_public_bind_all=bool(ppol.get("deny_public_bind_all", False)),
            external_network_prefix_allowlist=[str(x) for x in allowlist],
        )
        projects: Dict[str, ComposeProjectRef] = {}
        for name, p in (data.get("projects") or {}).items():
            projects[name] = ComposeProjectRef(
                name=name,
                working_dir=p.get("working_dir"),
                config_files=list(p.get("config_files") or []),
                environment_file=p.get("environment_file"),
            )
        return AppConfig(projects=projects, policies=policies)

    def save(self, cfg: AppConfig) -> None:
        data = {
            "policies": {
                "default_bind_ip": cfg.policies.default_bind_ip,
                "require_explicit_public": cfg.policies.require_explicit_public,
                "allow_privileged_ports": cfg.policies.allow_privileged_ports,
                "deny_public_bind_all": cfg.policies.deny_public_bind_all,
                "external_network_prefix_allowlist": list(cfg.policies.external_network_prefix_allowlist or []),
            },
            "projects": {
                name: {
                    "working_dir": ref.working_dir,
                    "config_files": list(ref.config_files),
                    "environment_file": ref.environment_file,
                }
                for name, ref in (cfg.projects or {}).items()
            }
        }
        self.path.write_text(yaml.safe_dump(data, sort_keys=True), encoding="utf-8")

    def overrides_dir(self) -> Path:
        d = self.state_dir / "overrides"
        d.mkdir(parents=True, exist_ok=True)
        return d

    def override_file(self, project: str) -> Path:
        return self.overrides_dir() / f"{project}.override.yaml"

    def events_log(self) -> Path:
        d = self.state_dir / "events"
        d.mkdir(parents=True, exist_ok=True)
        return d / "docker_events.jsonl"

    def health_log(self) -> Path:
        d = self.state_dir / "health"
        d.mkdir(parents=True, exist_ok=True)
        return d / "health_samples.jsonl"
