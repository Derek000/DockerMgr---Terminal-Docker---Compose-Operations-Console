from dockermgr.config import PolicyConfig
from dockermgr.policy import normalise_ports, allow_external_network_creation


def test_normalise_ports_applies_default_bind_ip():
    policy = PolicyConfig(default_bind_ip="127.0.0.1")
    ports, findings = normalise_ports(["8080:80"], policy)
    assert ports == ["127.0.0.1:8080:80"]
    assert any(f.code == "default_bind_ip_applied" for f in findings)


def test_normalise_ports_blocks_privileged_by_default():
    policy = PolicyConfig(default_bind_ip="127.0.0.1", allow_privileged_ports=False)
    ports, findings = normalise_ports(["80:80"], policy)
    assert any(f.code == "privileged_port" and f.level == "error" for f in findings)


def test_external_network_allowlist():
    policy = PolicyConfig(external_network_prefix_allowlist=["corp_", "madrock_"])
    assert allow_external_network_creation("corp_net", policy)
    assert not allow_external_network_creation("random_net", policy)
