from dockermgr.docker_service import DockerService


def test_extract_ports_handles_none():
    attrs = {"NetworkSettings": {"Ports": {"80/tcp": None}}}
    ports = DockerService._extract_ports(attrs)
    assert len(ports) == 1
    assert ports[0].container_port == "80/tcp"
    assert ports[0].host_port is None


def test_extract_ports_maps_hosts():
    attrs = {"NetworkSettings": {"Ports": {"80/tcp": [{"HostIp": "0.0.0.0", "HostPort": "8080"}]}}}
    ports = DockerService._extract_ports(attrs)
    assert len(ports) == 1
    assert ports[0].host_ip == "0.0.0.0"
    assert ports[0].host_port == "8080"
