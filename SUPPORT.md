# Support & Troubleshooting

## Common issues

### Docker daemon not reachable
- Ensure Docker is running
- Ensure your user can access the Docker socket:
  - Linux: `sudo usermod -aG docker $USER` then log out/in
  - Or run with sudo (not recommended for day-to-day)

### Compose actions fail
- Confirm `docker compose version` works
- Confirm the project's `working_dir` and `config_files` are correct:
  - Menu → Projects → select → Register

### Port conflict warnings
- `dockermgr` checks both:
  - existing Docker published ports
  - host listening ports (LISTEN/bound)
- You can proceed, but it often indicates the new mapping will fail.

## Logging
Logs are printed to stderr (console) with timestamps.
To capture logs:

```bash
dockermgr menu 2>dockermgr.log
```

## Reporting bugs
Include:
- `dockermgr --version`
- OS + Python version
- Docker Engine + Compose versions
- An incident bundle (`dockermgr incident-export ...`) with sensitive fields reviewed/redacted if required
