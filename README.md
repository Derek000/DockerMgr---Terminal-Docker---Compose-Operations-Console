# dockermgr — Docker and Compose Management CLI (Live Dashboard + Menu Drill-Down)

`dockermgr` is a terminal first, SSH-friendly Docker management application with:

- **Live front page dashboard**: host resources, compose projects, containers, images, and **recent Docker events**.
- **Menu-driven drill-down**: per-container inspection/logs/stats and compose project actions.
- **Compose projects as first-class entities** (discovered from labels or registered).
- **Reconfigure wizard** (CPU/mem, env overrides, env_file, ports, networks, secrets) with **diff preview** and **guardrails**.
- **Incident bundle export**: snapshot + recent events/health + config/overrides in one zip.
- **Docker network management**: list/inspect/create/remove with safety checks.

> Safety: access to the Docker socket is powerful. `dockermgr` defaults to **read-only** for operational actions.

---

## Install

```bash
python -m venv .venv
source .venv/bin/activate
pip install -U pip
pip install -e ".[dev]"
```

---

## Run

### Live dashboard
```bash
dockermgr dashboard
```

### Interactive operator console
```bash
dockermgr menu
```

---

## Reconfigure (operator-friendly)

From the menu:
- Projects → select → Reconfigure:
  - Edit service: CPU/mem, env, env_file, ports, networks, secrets
  - Networks: define internal/external networks for compose override
  - Secrets: file-based secrets definition
  - Preview diff: unified diff of changes
  - Apply: checks port conflicts, offers to create missing external networks, prompts for recreate

Override files:
- `~/.local/state/dockermgr/overrides/<project>.override.yaml`

Apply uses:
- `docker compose --compatibility up -d ...`

---

## Guardrails

- **Diff preview** shown before apply.
- **Port conflict checks** warn if requested host ports are already in use:
  - by an existing container binding
  - by a host process (LISTEN/bound)

---

## Secrets support

Easy mode (recommended): file-based secrets in compose override:
- Project secrets: `secrets: { name: { file: /path/to/secret } }`
- Attach per service: `services.<svc>.secrets: [name]`

This stays menu-driven (minimal config file editing).

---

## Networks

### Host-level Docker networks (menu + CLI)

Menu:
- Networks → list/inspect/create/remove

CLI:
```bash
dockermgr networks
dockermgr network-create mynet --read-only=false
dockermgr network-rm mynet --read-only=false
```

### Compose networks

Use Reconfigure → Networks wizard:
- define internal (compose-created) networks
- define external networks (apply can create them if missing)

---

## Incident bundle export

Menu:
- Incident → export zip

CLI:
```bash
dockermgr incident-export --out ./dockermgr_incident.zip --minutes 30
```

Output includes:
- snapshot.json
- docker_events_recent.jsonl
- health_samples_recent.jsonl
- config.yaml (if present)
- overrides/*

---

## Policy defaults (safe-by-default)

`dockermgr` applies operator-friendly safety defaults when you reconfigure services.

Default policies (configurable in `~/.config/dockermgr/config.yaml`):
- **default_bind_ip = 127.0.0.1**: if you enter `8080:80`, it becomes `127.0.0.1:8080:80`
- **allow_privileged_ports = false**: blocks host ports `<1024` unless explicitly allowed
- **deny_public_bind_all = false**: optional hard block for `0.0.0.0` binds
- **external_network_prefix_allowlist**: optional prefix allowlist to constrain creation of external networks

Example config:

```yaml
policies:
  default_bind_ip: "127.0.0.1"
  require_explicit_public: true
  allow_privileged_ports: false
  deny_public_bind_all: false
  external_network_prefix_allowlist:
    - "madrock_"
    - "corp_"
```

## Dry-run apply

During dry-run, dockermgr also prints an **Impact summary** (conservative):
- CREATE: service has no running container
- NO_CHANGE: no material differences detected
- RECREATE_LIKELY: differences detected (ports/env keys/networks/image/resources)
- SCALE: replica count differs (if specified)


When applying a reconfiguration, the menu offers **Dry-run only**:
- Runs `docker compose config` using your override file(s)
- Performs port conflict checks + policy checks
- Does **not** start/stop/recreate containers

This is intended for safe change review during operations.


## Tests

```bash
pytest
```

---

## License

MIT
