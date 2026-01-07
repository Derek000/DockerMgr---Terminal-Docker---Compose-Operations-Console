from __future__ import annotations

import logging
import os
from pathlib import Path
from logging.handlers import RotatingFileHandler


def configure_logging(log_level: str = "INFO") -> None:
    level = getattr(logging, log_level.upper(), logging.INFO)

    # Follow Linux-ish state dir; fallback to ~/.dockermgr
    state_dir = Path(os.environ.get("XDG_STATE_HOME", Path.home() / ".local" / "state")) / "dockermgr"
    log_dir = state_dir / "logs"
    log_dir.mkdir(parents=True, exist_ok=True)

    logfile = log_dir / "dockermgr.log"

    root = logging.getLogger()
    root.setLevel(level)

    fmt = logging.Formatter(
        fmt="%(asctime)s %(levelname)s [%(name)s] %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )

    # Console handler
    ch = logging.StreamHandler()
    ch.setLevel(level)
    ch.setFormatter(fmt)
    root.addHandler(ch)

    # Rotating file handler
    fh = RotatingFileHandler(logfile, maxBytes=2_000_000, backupCount=5, encoding="utf-8")
    fh.setLevel(level)
    fh.setFormatter(fmt)
    root.addHandler(fh)
