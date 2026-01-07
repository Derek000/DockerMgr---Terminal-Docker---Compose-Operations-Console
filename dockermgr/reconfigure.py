from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, List, Optional

import yaml


@dataclass
class ServiceOverride:
    cpus: Optional[float] = None  # e.g., 0.5
    memory: Optional[str] = None  # e.g., "512M"
    environment: Dict[str, str] = field(default_factory=dict)
    env_file: Optional[str] = None
    ports: List[str] = field(default_factory=list)
    networks: List[str] = field(default_factory=list)
    secrets: List[str] = field(default_factory=list)


@dataclass
class ProjectOverride:
    services: Dict[str, ServiceOverride] = field(default_factory=dict)
    # New format: full compose network definitions
    networks: Dict[str, dict] = field(default_factory=dict)
    # Backwards-compatible: simple map of external networks
    networks_external: Dict[str, bool] = field(default_factory=dict)
    secrets: Dict[str, dict] = field(default_factory=dict)


def load_override(path: Path) -> ProjectOverride:
    if not path.exists():
        return ProjectOverride()
    data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    services: Dict[str, ServiceOverride] = {}
    for svc, spec in (data.get("services") or {}).items():
        env = (spec.get("environment") or {}) if isinstance(spec.get("environment"), dict) else {}
        ports = list(spec.get("ports") or [])
        nets = list(spec.get("networks") or [])
        env_file = spec.get("env_file")
        secrets = list(spec.get("secrets") or [])

        deploy = spec.get("deploy") or {}
        limits = ((deploy.get("resources") or {}).get("limits") or {})
        cpus = limits.get("cpus")
        mem = limits.get("memory")

        services[svc] = ServiceOverride(
            cpus=float(cpus) if cpus is not None else None,
            memory=str(mem) if mem is not None else None,
            environment={str(k): str(v) for k, v in env.items()},
            env_file=str(env_file) if env_file is not None else None,
            ports=[str(p) for p in ports],
            networks=[str(n) for n in nets],
            secrets=[str(s) for s in secrets],
        )
    networks = data.get("networks") or {}
    networks_external_legacy = data.get("networks_external") or {}

    # Derive simple external map from networks definitions
    networks_external = {str(k): True for k, v in (networks or {}).items() if isinstance(v, dict) and v.get("external") is True}
    # Merge legacy field if present
    for k, v in (networks_external_legacy or {}).items():
        networks_external[str(k)] = bool(v)

    secrets_doc = data.get("secrets") or {}
    return ProjectOverride(services=services, networks=dict(networks), networks_external=dict(networks_external), secrets=dict(secrets_doc))


def save_override(path: Path, override: ProjectOverride) -> None:
    doc: dict = {"services": {}}
    for svc, o in (override.services or {}).items():
        s: dict = {}
        if o.environment:
            s["environment"] = dict(sorted(o.environment.items()))
        if o.env_file:
            s["env_file"] = o.env_file
        if o.ports:
            s["ports"] = list(o.ports)
        if o.networks:
            s["networks"] = list(o.networks)
        if o.secrets:
            s["secrets"] = list(o.secrets)

        if o.cpus is not None or o.memory is not None:
            s["deploy"] = {"resources": {"limits": {}}}
            if o.cpus is not None:
                s["deploy"]["resources"]["limits"]["cpus"] = f"{o.cpus:.2f}".rstrip("0").rstrip(".")
            if o.memory is not None:
                s["deploy"]["resources"]["limits"]["memory"] = o.memory

        doc["services"][svc] = s

    # If caller used legacy networks_external, materialise into compose networks unless explicit networks provided.
    if override.networks_external and not override.networks:
        doc["networks"] = {name: {"external": True} for name, is_ext in override.networks_external.items() if is_ext}
        doc["networks_external"] = dict(override.networks_external)
    elif override.networks:
        doc["networks"] = override.networks
        # Also expose a derived legacy field for readability/back-compat.
        doc["networks_external"] = {name: True for name, spec in override.networks.items() if isinstance(spec, dict) and spec.get("external") is True}
    if override.secrets:
        doc["secrets"] = override.secrets

    path.write_text(yaml.safe_dump(doc, sort_keys=False), encoding="utf-8")


def yaml_dump_override(override: ProjectOverride) -> str:
    doc: dict = {"services": {}}
    for svc, o in (override.services or {}).items():
        s: dict = {}
        if o.environment:
            s["environment"] = dict(sorted(o.environment.items()))
        if o.env_file:
            s["env_file"] = o.env_file
        if o.ports:
            s["ports"] = list(o.ports)
        if o.networks:
            s["networks"] = list(o.networks)
        if o.secrets:
            s["secrets"] = list(o.secrets)
        if o.cpus is not None or o.memory is not None:
            s["deploy"] = {"resources": {"limits": {}}}
            if o.cpus is not None:
                s["deploy"]["resources"]["limits"]["cpus"] = f"{o.cpus:.2f}".rstrip("0").rstrip(".")
            if o.memory is not None:
                s["deploy"]["resources"]["limits"]["memory"] = o.memory
        doc["services"][svc] = s
    # If caller used legacy networks_external, materialise into compose networks unless explicit networks provided.
    if override.networks_external and not override.networks:
        doc["networks"] = {name: {"external": True} for name, is_ext in override.networks_external.items() if is_ext}
        doc["networks_external"] = dict(override.networks_external)
    elif override.networks:
        doc["networks"] = override.networks
        # Also expose a derived legacy field for readability/back-compat.
        doc["networks_external"] = {name: True for name, spec in override.networks.items() if isinstance(spec, dict) and spec.get("external") is True}
    if override.secrets:
        doc["secrets"] = override.secrets
    return yaml.safe_dump(doc, sort_keys=False)
