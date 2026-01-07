# Contributing

## Development setup
```bash
python -m venv .venv
source .venv/bin/activate
pip install -e ".[dev]"
pytest
```

## Code style
- Favour small, testable functions
- Add docstrings for public functions and safety-sensitive logic
- Logging should be structured and avoid printing secrets

## Pull requests
- Include tests for changes where practical
- Update docs when adding user-facing features
- Update CHANGELOG for notable changes
