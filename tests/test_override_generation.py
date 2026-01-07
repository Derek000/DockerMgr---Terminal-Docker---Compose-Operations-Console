from pathlib import Path
from dockermgr.reconfigure import ProjectOverride, ServiceOverride, save_override, load_override


def test_override_roundtrip(tmp_path: Path):
    p = tmp_path / "o.yaml"
    po = ProjectOverride(
        services={
            "web": ServiceOverride(
                cpus=0.5,
                memory="512M",
                environment={"A": "1"},
                ports=["8080:80"],
                networks=["front"],
            )
        },
        networks_external={"front": True},
    )
    save_override(p, po)
    po2 = load_override(p)
    assert po2.services["web"].cpus == 0.5
    assert po2.services["web"].memory == "512M"
    assert po2.services["web"].environment["A"] == "1"
    assert po2.services["web"].ports == ["8080:80"]
    assert po2.services["web"].networks == ["front"]
    assert po2.networks_external["front"] is True
