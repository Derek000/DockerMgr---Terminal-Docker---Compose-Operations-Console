from __future__ import annotations

"""Change impact analysis for Docker Compose projects.

Docker Compose does not provide an official "plan" output that tells you what will be
created/recreated/updated. For an operator-friendly dry-run, we produce a conservative
impact summary by comparing the *effective compose config* (from `docker compose config`)
against the live container configuration (from `docker inspect`).

Principles:
- Prefer false-positives over false-negatives (warn when unsure).
- Avoid secrets leakage (never print env var values by default).
"""

from dataclasses import dataclass
from typing import Dict, List, Optional, Tuple, Any

import yaml


@dataclass(frozen=True)
class ImpactItem:
    service: str
    status: str  # NO_CHANGE | RECREATE_LIKELY | CREATE | SCALE | UNKNOWN
    reasons: List[str]


def _env_list_to_dict(env_list: Any) -> Dict[str, str]:
    if not env_list:
        return {}
    if isinstance(env_list, dict):
        return {str(k): str(v) for k, v in env_list.items()}
    out: Dict[str, str] = {}
    for item in env_list:
        if not isinstance(item, str) or "=" not in item:
            continue
        k, v = item.split("=", 1)
        out[str(k)] = str(v)
    return out


def _normalise_ports_from_compose(service_cfg: Dict[str, Any]) -> List[Tuple[Optional[str], Optional[int], int, str]]:
    """Return a normalised list of (host_ip, published, target, protocol) for compose ports.

    Compose config output often uses long form:
      - target: 80
        published: "8080"
        protocol: tcp
        mode: host

    It may also include short form strings.
    """
    ports = service_cfg.get("ports") or []
    out: List[Tuple[Optional[str], Optional[int], int, str]] = []
    for p in ports:
        if isinstance(p, str):
            # best-effort parse for strings like "127.0.0.1:8080:80/tcp" or "8080:80"
            proto = "tcp"
            s = p.strip()
            if "/" in s:
                s, proto = s.rsplit("/", 1)
                proto = proto.lower()
            host_ip = None
            parts = s.split(":")
            try:
                if len(parts) == 2:
                    published = int(parts[0])
                    target = int(parts[1])
                elif len(parts) == 3:
                    host_ip = parts[0]
                    published = int(parts[1])
                    target = int(parts[2])
                else:
                    continue
            except ValueError:
                continue
            out.append((host_ip, published, target, proto))
        elif isinstance(p, dict):
            target = p.get("target")
            published = p.get("published")
            proto = (p.get("protocol") or "tcp").lower()
            host_ip = p.get("host_ip") or p.get("ip")  # not always present
            try:
                target_i = int(target)
            except Exception:
                continue
            pub_i: Optional[int]
            try:
                pub_i = int(published) if published is not None else None
            except Exception:
                pub_i = None
            out.append((str(host_ip) if host_ip else None, pub_i, target_i, proto))
    # sort stable
    out.sort(key=lambda x: (x[0] or "", x[1] or -1, x[2], x[3]))
    return out


def _normalise_ports_from_inspect(inspect: Dict[str, Any]) -> List[Tuple[Optional[str], Optional[int], int, str]]:
    net = (inspect.get("NetworkSettings") or {})
    ports = (net.get("Ports") or {})  # {"80/tcp": [{"HostIp":"0.0.0.0","HostPort":"8080"}], ...}
    out: List[Tuple[Optional[str], Optional[int], int, str]] = []
    for cport, bindings in ports.items():
        if not cport:
            continue
        if "/" in cport:
            port_s, proto = cport.split("/", 1)
            proto = proto.lower()
        else:
            port_s, proto = cport, "tcp"
        try:
            target = int(port_s)
        except Exception:
            continue
        if not bindings:
            # exposed but not published
            out.append((None, None, target, proto))
            continue
        for b in bindings:
            hip = b.get("HostIp")
            hp = b.get("HostPort")
            try:
                pub = int(hp) if hp is not None else None
            except Exception:
                pub = None
            out.append((str(hip) if hip else None, pub, target, proto))
    out.sort(key=lambda x: (x[0] or "", x[1] or -1, x[2], x[3]))
    return out


def _parse_memory_to_bytes(mem: Optional[str]) -> Optional[int]:
    if mem is None:
        return None
    s = str(mem).strip()
    if not s:
        return None
    # Common compose units: b, k, m, g (also kb/mb/gb)
    units = {"b": 1, "k": 1024, "kb": 1024, "m": 1024**2, "mb": 1024**2, "g": 1024**3, "gb": 1024**3}
    num = ""
    unit = ""
    for ch in s:
        if ch.isdigit() or ch == ".":
            num += ch
        else:
            unit += ch
    unit = unit.strip().lower() or "b"
    if unit not in units:
        return None
    try:
        val = float(num)
    except Exception:
        return None
    return int(val * units[unit])


def _desired_limits(service_cfg: Dict[str, Any]) -> Tuple[Optional[float], Optional[int]]:
    deploy = service_cfg.get("deploy") or {}
    limits = ((deploy.get("resources") or {}).get("limits") or {})
    cpus = limits.get("cpus")
    mem = limits.get("memory")
    cpu_f: Optional[float]
    try:
        cpu_f = float(cpus) if cpus is not None else None
    except Exception:
        cpu_f = None
    mem_b = _parse_memory_to_bytes(mem) if mem is not None else None
    return cpu_f, mem_b


def _current_limits(inspect: Dict[str, Any]) -> Tuple[Optional[float], Optional[int]]:
    hc = (inspect.get("HostConfig") or {})
    nano = hc.get("NanoCpus")
    mem = hc.get("Memory")
    cpu_f: Optional[float] = None
    try:
        if nano:
            cpu_f = float(nano) / 1e9
    except Exception:
        cpu_f = None
    mem_i: Optional[int] = None
    try:
        if mem:
            mem_i = int(mem)
    except Exception:
        mem_i = None
    return cpu_f, mem_i


def _networks_from_compose(service_cfg: Dict[str, Any]) -> List[str]:
    nets = service_cfg.get("networks")
    if not nets:
        return []
    if isinstance(nets, dict):
        return sorted([str(k) for k in nets.keys()])
    if isinstance(nets, list):
        return sorted([str(x) for x in nets])
    return []


def _networks_from_inspect(inspect: Dict[str, Any]) -> List[str]:
    net = (inspect.get("NetworkSettings") or {})
    nets = (net.get("Networks") or {})
    if isinstance(nets, dict):
        return sorted([str(k) for k in nets.keys()])
    return []


def _image_from_inspect(inspect: Dict[str, Any]) -> Optional[str]:
    cfg = inspect.get("Config") or {}
    return cfg.get("Image")


def _image_from_compose(service_cfg: Dict[str, Any]) -> Optional[str]:
    img = service_cfg.get("image")
    return str(img) if img else None


def impact_summary(
    compose_config_yaml: str,
    containers_by_service: Dict[str, List[Dict[str, Any]]],
) -> List[ImpactItem]:
    """Compute conservative impact summary.

    Args:
        compose_config_yaml: stdout from `docker compose config` (YAML)
        containers_by_service: mapping of service->list of docker inspect dicts for current containers

    Returns:
        List of ImpactItem sorted by service name.
    """
    try:
        cfg = yaml.safe_load(compose_config_yaml) or {}
    except Exception:
        return [ImpactItem(service="*", status="UNKNOWN", reasons=["Failed to parse compose config YAML"])]

    services = cfg.get("services") or {}
    results: List[ImpactItem] = []

    for svc, svc_cfg in services.items():
        reasons: List[str] = []

        desired_img = _image_from_compose(svc_cfg)
        desired_env = _env_list_to_dict(svc_cfg.get("environment"))
        desired_ports = _normalise_ports_from_compose(svc_cfg)
        desired_nets = _networks_from_compose(svc_cfg)
        desired_cpu, desired_mem = _desired_limits(svc_cfg)
        desired_replicas = None
        try:
            desired_replicas = int((svc_cfg.get("deploy") or {}).get("replicas")) if (svc_cfg.get("deploy") or {}).get("replicas") is not None else None
        except Exception:
            desired_replicas = None

        current_list = containers_by_service.get(svc, []) or []
        if not current_list:
            status = "CREATE"
            results.append(ImpactItem(service=svc, status=status, reasons=["No running container found for service"]))
            continue

        # Scaling summary (if replicas specified)
        if desired_replicas is not None and desired_replicas != len(current_list):
            results.append(ImpactItem(service=svc, status="SCALE", reasons=[f"Replica count differs: desired={desired_replicas}, current={len(current_list)}"]))
            # Continue with diffing first container for config impact.
        inspect = current_list[0]

        current_img = _image_from_inspect(inspect)
        if desired_img and current_img and desired_img != current_img:
            reasons.append("Image differs")

        # Env comparison (keys only; avoid value leakage in summaries)
        current_env = _env_list_to_dict((inspect.get("Config") or {}).get("Env"))
        if set(desired_env.keys()) != set(current_env.keys()):
            reasons.append("Environment variable keys differ")

        # Ports comparison
        current_ports = _normalise_ports_from_inspect(inspect)
        if desired_ports != current_ports:
            reasons.append("Published ports differ")

        # Networks comparison
        current_nets = _networks_from_inspect(inspect)
        if desired_nets and desired_nets != current_nets:
            reasons.append("Networks differ")

        # Resource limits (approx; compose applies via --compatibility)
        cur_cpu, cur_mem = _current_limits(inspect)
        if desired_cpu is not None and cur_cpu is not None:
            # round for stability
            if round(desired_cpu, 2) != round(cur_cpu, 2):
                reasons.append("CPU limit differs")
        elif desired_cpu is not None and cur_cpu is None:
            reasons.append("CPU limit set in compose but not detected in container")

        if desired_mem is not None and cur_mem is not None:
            if int(desired_mem) != int(cur_mem):
                reasons.append("Memory limit differs")
        elif desired_mem is not None and cur_mem is None:
            reasons.append("Memory limit set in compose but not detected in container")

        status = "NO_CHANGE" if not reasons else "RECREATE_LIKELY"
        results.append(ImpactItem(service=svc, status=status, reasons=reasons or ["No material differences detected"]))

    results.sort(key=lambda x: x.service.lower())
    return results
