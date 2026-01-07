# Installation (Enterprise-friendly)

## Supported platforms
- Linux (recommended)
- macOS (best effort)
- Windows: supported when running inside WSL2 with access to a Docker daemon

## Requirements
- Python 3.10+
- Docker Engine
- Docker Compose v2 plugin (`docker compose ...`)
- Permissions to access the Docker socket:
  - either root, or a user in the `docker` group (Linux)

## Recommended install (pipx)
`pipx` keeps the tool isolated and easy to upgrade.

```bash
python3 -m pip install --user pipx
pipx ensurepath
pipx install .
dockermgr --help
```

## Developer / editable install (virtualenv)

```bash
python -m venv .venv
source .venv/bin/activate
pip install -U pip
pip install -e ".[dev]"
pytest
dockermgr menu
```

## Security note: Docker socket
Access to `/var/run/docker.sock` is equivalent to root on most hosts.
Operate with least privilege and prefer `--read-only` mode unless you explicitly need to perform actions.
