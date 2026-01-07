# Changelog

## 0.4.1
- Dry-run prints conservative container impact summary (create/recreate/scale/no-change)

## 0.4.0
- Policy defaults for ports + external network creation allowlist
- Dry-run apply (runs `docker compose config` with overrides, no runtime changes)
- Expanded documentation and GitHub-ready project scaffolding

## 0.3.0
- Compose projects as first-class entities (discover + register)
- Reconfigure wizard (CPU/mem/env/ports/networks/secrets) with diff preview + guardrails
- Incident bundle exporter
- Docker network management
