from dockermgr.impact import impact_summary


def test_impact_create_when_no_container():
    cfg = """services:
  web:
    image: nginx:latest
    ports:
      - target: 80
        published: "8080"
        protocol: tcp
"""
    impacts = impact_summary(cfg, containers_by_service={})
    web = [i for i in impacts if i.service == "web"][0]
    assert web.status == "CREATE"


def test_impact_recreate_when_ports_differ():
    cfg = """services:
  web:
    image: nginx:latest
    ports:
      - target: 80
        published: "8080"
        protocol: tcp
"""
    inspect = {
        "Config": {"Image": "nginx:latest", "Env": ["A=1"]},
        "HostConfig": {"NanoCpus": 0, "Memory": 0},
        "NetworkSettings": {"Ports": {"80/tcp": [{"HostIp": "127.0.0.1", "HostPort": "9090"}]}},
    }
    impacts = impact_summary(cfg, containers_by_service={"web": [inspect]})
    web = [i for i in impacts if i.service == "web"][0]
    assert web.status == "RECREATE_LIKELY"
    assert any("ports" in r.lower() for r in web.reasons)
