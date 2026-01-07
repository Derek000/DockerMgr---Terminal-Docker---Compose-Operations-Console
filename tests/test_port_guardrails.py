from dockermgr.utils.port_guardrails import parse_compose_ports, detect_port_conflicts


def test_parse_compose_ports():
    ports = parse_compose_ports(["8080:80", "127.0.0.1:5353:5353/udp"])
    assert ports[0] == (None, 8080, "tcp")
    assert ports[1] == ("127.0.0.1", 5353, "udp")


def test_detect_conflicts_docker_binding():
    requested = [(None, 8080, "tcp")]
    conflicts = detect_port_conflicts(requested, docker_bindings={(8080, "tcp")})
    assert any(c.reason == "docker_binding" for c in conflicts)
