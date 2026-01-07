from __future__ import annotations

import re
from dataclasses import dataclass
from typing import List, Optional, Set, Tuple

import psutil

_PORT_RE = re.compile(
    r"""^
    (?:
        (?P<ip>\d+\.\d+\.\d+\.\d+):
    )?
    (?P<host>\d+):
    (?P<container>\d+)
    (?:/(?P<proto>tcp|udp))?
    $""",
    re.VERBOSE,
)


@dataclass(frozen=True)
class PortConflict:
    host_ip: Optional[str]
    host_port: int
    proto: str
    reason: str
    detail: str


def parse_compose_ports(port_lines: List[str]) -> List[Tuple[Optional[str], int, str]]:
    out: List[Tuple[Optional[str], int, str]] = []
    for p in port_lines:
        m = _PORT_RE.match(p.strip())
        if not m:
            continue
        ip = m.group("ip")
        host = int(m.group("host"))
        proto = (m.group("proto") or "tcp").lower()
        out.append((ip, host, proto))
    return out


def host_listening_ports() -> Set[Tuple[int, str]]:
    used: Set[Tuple[int, str]] = set()
    try:
        conns = psutil.net_connections(kind="inet")
    except Exception:
        return used

    for c in conns:
        if not c.laddr:
            continue
        proto = "tcp" if c.type == getattr(psutil, "SOCK_STREAM", 1) else "udp"
        if proto == "tcp":
            if c.status == psutil.CONN_LISTEN:
                used.add((int(c.laddr.port), proto))
        else:
            used.add((int(c.laddr.port), proto))
    return used


def detect_port_conflicts(
    requested: List[Tuple[Optional[str], int, str]],
    docker_bindings: Set[Tuple[int, str]],
) -> List[PortConflict]:
    conflicts: List[PortConflict] = []
    host_used = host_listening_ports()

    for ip, port, proto in requested:
        if (port, proto) in docker_bindings:
            conflicts.append(
                PortConflict(
                    host_ip=ip,
                    host_port=port,
                    proto=proto,
                    reason="docker_binding",
                    detail=f"Host port {port}/{proto} is already published by an existing container.",
                )
            )
        if (port, proto) in host_used:
            conflicts.append(
                PortConflict(
                    host_ip=ip,
                    host_port=port,
                    proto=proto,
                    reason="host_listen",
                    detail=f"Host port {port}/{proto} is already in use by a host process (LISTEN/bound).",
                )
            )

    uniq = {}
    for c in conflicts:
        uniq[(c.host_ip, c.host_port, c.proto, c.reason)] = c
    return list(uniq.values())
