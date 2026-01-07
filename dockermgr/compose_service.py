from __future__ import annotations

import logging
import shutil
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import List, Optional, Sequence

from .models import ComposeProjectRef

log = logging.getLogger(__name__)


@dataclass(frozen=True)
class ComposeRunResult:
    rc: int
    stdout: str
    stderr: str


class ComposeService:
    """Controls Docker Compose projects via `docker compose` CLI (Compose v2).

    Why CLI?
      - Compose orchestration isn't fully exposed via Docker SDK.
      - CLI supports `up`, `down`, `restart`, `pull`, and `config` validation.

    Safety:
      - No shell=True
      - argv list only
    """

    def __init__(self, docker_compose_cmd: str = "docker", timeout_s: int = 60):
        self.docker_compose_cmd = docker_compose_cmd
        self.timeout_s = timeout_s

    def is_available(self) -> bool:
        return bool(shutil.which(self.docker_compose_cmd))

    def _compose_argv(self, project: ComposeProjectRef, extra_files: Optional[List[str]] = None) -> List[str]:
        argv = [self.docker_compose_cmd, "compose"]
        # project name: ensures correct targeting even if running elsewhere
        argv += ["-p", project.name]

        files = list(project.config_files or [])
        if extra_files:
            files += extra_files
        for f in files:
            argv += ["-f", f]

        if project.working_dir:
            argv += ["--project-directory", project.working_dir]

        return argv

    def run(self, project: ComposeProjectRef, args: Sequence[str], extra_files: Optional[List[str]] = None) -> ComposeRunResult:
        if not self.is_available():
            raise RuntimeError("`docker` command not found. Install Docker CLI with Compose v2 support.")

        argv = self._compose_argv(project, extra_files=extra_files) + list(args)
        log.debug("Running compose: %s", argv)
        p = subprocess.run(argv, capture_output=True, text=True, timeout=self.timeout_s)
        return ComposeRunResult(rc=p.returncode, stdout=p.stdout, stderr=p.stderr)

    def up(
        self,
        project: ComposeProjectRef,
        extra_files: Optional[List[str]] = None,
        pull: bool = False,
        force_recreate: bool = False,
        compatibility: bool = True,
    ) -> ComposeRunResult:
        args: List[str] = []
        if compatibility:
            args.append("--compatibility")
        args += ["up", "-d", "--remove-orphans"]
        if pull:
            args += ["--pull", "always"]
        if force_recreate:
            args.append("--force-recreate")
        return self.run(project, args=args, extra_files=extra_files)

    def down(self, project: ComposeProjectRef, extra_files: Optional[List[str]] = None) -> ComposeRunResult:
        return self.run(project, args=["down"], extra_files=extra_files)

    def restart(self, project: ComposeProjectRef, extra_files: Optional[List[str]] = None) -> ComposeRunResult:
        return self.run(project, args=["restart"], extra_files=extra_files)

    def pull(self, project: ComposeProjectRef, extra_files: Optional[List[str]] = None) -> ComposeRunResult:
        return self.run(project, args=["pull"], extra_files=extra_files)

    def config(self, project: ComposeProjectRef, extra_files: Optional[List[str]] = None) -> ComposeRunResult:
        return self.run(project, args=["config"], extra_files=extra_files)

    def ps(self, project: ComposeProjectRef, extra_files: Optional[List[str]] = None) -> ComposeRunResult:
        # JSON format supported by newer compose; fallback handled by caller.
        return self.run(project, args=["ps"], extra_files=extra_files)
