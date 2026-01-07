from __future__ import annotations

"""Operational policies and safety defaults.

This module implements opinionated-but-configurable defaults to reduce common
operational mistakes when managing Docker Compose projects via a terminal UI.

Design goals:
- Prefer safe-by-default behaviour (localhost binds, avoid privileged ports).
- Make policy application visible (warnings + unified diff).
- Keep the operator in control (can override when needed).
"""

import re
from dataclasses import dataclass
from typing import List, Tuple, Optional

from .config import PolicyConfig


# Compose port formats we support in the UI:
# - "8080:80"
# - "127.0.0.1:8080:80"
# - "8080:80/tcp"
# - "127.0.0.1:5353:5353/udp"
_PORT_RE = re.compile(
    r"""^
    (?:(?P<ip>\d+\.\d+\.\d+\.\d+):)?
    (?P<host>\d+):
    (?P<container>\d+)
    (?:/(?P<proto>tcp|udp))?
    $""",
    re.VERBOSE,
)


@dataclass(frozen=True)
class PolicyFinding:
    level: str  # "warning" or "error"
    code: str
    message: str
    port_line: Optional[str] = None


def normalise_ports(port_lines: List[str], policy: PolicyConfig) -> Tuple[List[str], List[PolicyFinding]]:
    """Apply policy defaults to port lines.

    If a port mapping omits an IP (e.g. "8080:80"), we can prepend policy.default_bind_ip,
    producing "127.0.0.1:8080:80". This reduces accidental exposure on 0.0.0.0.

    Returns:
        (updated_port_lines, findings)
    """
    out: List[str] = []
    findings: List[PolicyFinding] = []

    for line in port_lines or []:
        s = line.strip()
        m = _PORT_RE.match(s)
        if not m:
            # Keep as-is; other compose formats (long syntax) may exist.
            out.append(s)
            continue

        ip = m.group("ip")
        host = int(m.group("host"))
        proto = (m.group("proto") or "tcp").lower()

        # Privileged port policy
        if host < 1024 and not policy.allow_privileged_ports:
            findings.append(
                PolicyFinding(
                    level="error",
                    code="privileged_port",
                    message=f"Host port {host}/{proto} is privileged (<1024) and is blocked by policy.",
                    port_line=s,
                )
            )

        # Block bind-all if configured
        if ip == "0.0.0.0" and policy.deny_public_bind_all:
            findings.append(
                PolicyFinding(
                    level="error",
                    code="bind_all_denied",
                    message=f"Binding to 0.0.0.0 for {host}/{proto} is blocked by policy.",
                    port_line=s,
                )
            )

        # Default bind IP
        if ip is None:
            if policy.default_bind_ip:
                s2 = f"{policy.default_bind_ip}:{s}"
                findings.append(
                    PolicyFinding(
                        level="warning",
                        code="default_bind_ip_applied",
                        message=f"Applied default bind IP {policy.default_bind_ip} to port mapping.",
                        port_line=s,
                    )
                )
                out.append(s2)
            else:
                # If no default bind IP, this likely means bind-all; warn if required.
                if policy.require_explicit_public:
                    findings.append(
                        PolicyFinding(
                            level="warning",
                            code="public_exposure_possible",
                            message=f"Port mapping '{s}' has no IP. This may publish on all interfaces.",
                            port_line=s,
                        )
                    )
                out.append(s)
        else:
            out.append(s)

    return out, findings


def allow_external_network_creation(network_name: str, policy: PolicyConfig) -> bool:
    """Return True if creating an external network is allowed by policy.

    If the allowlist is empty -> allow all (operator convenience).
    If non-empty -> require prefix match (basic guardrail).
    """
    allow = policy.external_network_prefix_allowlist or []
    if not allow:
        return True
    return any(network_name.startswith(prefix) for prefix in allow)
