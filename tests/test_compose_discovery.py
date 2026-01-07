from dockermgr.models import ContainerSummary
from dockermgr.docker_service import DockerService


def test_discover_compose_projects_best_effort(monkeypatch):
    # We monkeypatch inspect to supply labels
    ds = DockerService.__new__(DockerService)  # bypass init
    def fake_inspect(name):
        return {
            "Config": {"Labels": {
                "com.docker.compose.project": "p1",
                "com.docker.compose.project.working_dir": "/srv/p1",
                "com.docker.compose.project.config_files": "/srv/p1/compose.yaml",
            }}
        }
    ds.inspect = fake_inspect  # type: ignore

    containers = [
        ContainerSummary(
            id="abc",
            name="c1",
            image="img",
            status="running",
            state="running",
            created="",
            ports=[],
            health="N/A",
            restart_count=0,
            compose_project="p1",
            compose_service="web",
        )
    ]
    projects = DockerService.discover_compose_projects(ds, containers)  # type: ignore
    assert "p1" in projects
    assert projects["p1"].working_dir == "/srv/p1"
    assert projects["p1"].config_files == ["/srv/p1/compose.yaml"]
