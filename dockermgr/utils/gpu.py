from __future__ import annotations

import logging
import shutil
import subprocess
from typing import Optional

log = logging.getLogger(__name__)


def get_gpu_summary() -> Optional[str]:
    """Best-effort GPU summary.

    Uses `nvidia-smi` if present; otherwise returns None.
    """
    if not shutil.which("nvidia-smi"):
        return None

    # Query: name, utilisation, memory used/total
    cmd = [
        "nvidia-smi",
        "--query-gpu=name,utilization.gpu,memory.used,memory.total",
        "--format=csv,noheader,nounits",
    ]
    try:
        p = subprocess.run(cmd, check=True, capture_output=True, text=True, timeout=2)
        lines = [ln.strip() for ln in p.stdout.splitlines() if ln.strip()]
        if not lines:
            return None
        # Support multiple GPUs; summarise succinctly.
        parts = []
        for ln in lines:
            cols = [c.strip() for c in ln.split(",")]
            if len(cols) >= 4:
                name, util, mem_used, mem_total = cols[:4]
                parts.append(f"{name} {util}% {mem_used}/{mem_total}MiB")
            else:
                parts.append(ln)
        return " | ".join(parts)
    except Exception as e:
        log.debug("GPU detection failed: %s", e)
        return None
