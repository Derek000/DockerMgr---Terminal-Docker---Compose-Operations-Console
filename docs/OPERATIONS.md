# Operations guide

## Modes
- **dashboard**: live view (Ctrl+C to exit)
- **menu**: interactive operator console (recommended)

By default, operational actions are **disabled** in read-only mode.

## Configuration and state
- Config: `~/.config/dockermgr/config.yaml`
- State: `~/.local/state/dockermgr/`
  - overrides: `overrides/<project>.override.yaml`
  - events: `events/docker_events.jsonl`
  - health: `health/health_samples.jsonl`

## Reconfigure workflow (recommended)
1. Menu → Projects → select project → Reconfigure
2. Edit service limits/env/ports/networks/secrets
3. Preview diff
4. Apply:
   - policy defaults (optional)
   - port conflict checks
   - **dry-run** (`docker compose config`)
   - apply (`docker compose up -d`), optional recreate

## Incident bundles
Use incident export when debugging:
- captures host + container state snapshot
- captures recent docker events and health samples
- captures config + overrides

This is designed to be attachable to a ticket or shared internally.
