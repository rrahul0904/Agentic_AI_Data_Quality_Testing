"""Governed SSH-backed remote workspaces.

This is distinct from database SSH port forwarding: it provides a project-root-scoped
remote filesystem and terminal surface for ADE coding/data-engineering sessions.
"""

from __future__ import annotations

import base64
from dataclasses import dataclass
from pathlib import PurePosixPath
import re
import shlex
import subprocess
from typing import Any, Callable, Sequence


RunFactory = Callable[..., subprocess.CompletedProcess[str]]
_HOST = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]*$")
_USER = re.compile(r"^[A-Za-z_][A-Za-z0-9_.-]*$")


@dataclass(frozen=True)
class RemoteWorkspaceConfig:
    host: str
    user: str
    root: str
    port: int = 22
    identity_file: str | None = None
    connect_timeout_seconds: int = 10


class SSHRemoteWorkspace:
    """Remote workspace with deterministic command construction and root confinement."""

    def __init__(self, config: RemoteWorkspaceConfig, *, runner: RunFactory | None = None) -> None:
        self.config = config
        self._run = runner or subprocess.run
        if not _HOST.fullmatch(config.host.strip()):
            raise ValueError("invalid SSH host")
        if not _USER.fullmatch(config.user.strip()):
            raise ValueError("invalid SSH user")
        if not 1 <= int(config.port) <= 65535:
            raise ValueError("invalid SSH port")
        root = PurePosixPath(config.root)
        if not root.is_absolute() or ".." in root.parts:
            raise ValueError("remote workspace root must be an absolute normalized path")
        self.root = root

    def _ssh_base(self) -> list[str]:
        command = [
            "ssh",
            "-o",
            "BatchMode=yes",
            "-o",
            f"ConnectTimeout={max(1, min(int(self.config.connect_timeout_seconds), 120))}",
            "-p",
            str(int(self.config.port)),
        ]
        if self.config.identity_file:
            command += ["-i", self.config.identity_file]
        command.append(f"{self.config.user}@{self.config.host}")
        return command

    def _path(self, relative: str = ".") -> PurePosixPath:
        raw = PurePosixPath(relative or ".")
        if raw.is_absolute() or ".." in raw.parts:
            raise ValueError("remote path must stay inside the workspace root")
        normalized = self.root.joinpath(raw)
        if not str(normalized).startswith(str(self.root).rstrip("/") + "/") and normalized != self.root:
            raise ValueError("remote path escapes workspace root")
        return normalized

    def command(self, script: str) -> list[str]:
        return [*self._ssh_base(), "--", "sh", "-lc", script]

    def _exec(self, script: str, *, timeout: int = 60, check: bool = False) -> dict[str, Any]:
        command = self.command(script)
        try:
            result = self._run(
                command,
                capture_output=True,
                text=True,
                timeout=max(1, min(int(timeout), 3600)),
                check=False,
            )
        except FileNotFoundError:
            return {"status": "SKIP_EXTERNAL", "reason": "ssh client is not installed", "command": command}
        payload = {
            "status": "PASS" if result.returncode == 0 else "FAIL",
            "returncode": int(result.returncode),
            "stdout": result.stdout[-200_000:],
            "stderr": result.stderr[-20_000:],
            "command": command,
        }
        if check and result.returncode != 0:
            raise RuntimeError(result.stderr[-2000:] or f"remote command exited {result.returncode}")
        return payload

    def status(self) -> dict[str, Any]:
        root = shlex.quote(str(self.root))
        result = self._exec(f"test -d {root} && printf 'ADE_REMOTE_READY\\n'", timeout=15)
        return {
            **result,
            "host": self.config.host,
            "user": self.config.user,
            "root": str(self.root),
        }

    def list_files(self, relative: str = ".", *, max_depth: int = 4, limit: int = 2000) -> dict[str, Any]:
        target = shlex.quote(str(self._path(relative)))
        depth = max(1, min(int(max_depth), 20))
        bounded = max(1, min(int(limit), 20_000))
        script = (
            f"cd {shlex.quote(str(self.root))} && "
            f"find {target} -maxdepth {depth} -type f -print | LC_ALL=C sort | head -n {bounded}"
        )
        result = self._exec(script)
        files = [line.strip() for line in result.get("stdout", "").splitlines() if line.strip()]
        result["files"] = files
        result["count"] = len(files)
        return result

    def read_text(self, relative: str, *, max_bytes: int = 2_000_000) -> dict[str, Any]:
        target = shlex.quote(str(self._path(relative)))
        bounded = max(1, min(int(max_bytes), 20_000_000))
        result = self._exec(f"head -c {bounded} -- {target}")
        result.update({"path": relative, "max_bytes": bounded})
        return result

    def write_text(
        self,
        relative: str,
        content: str,
        *,
        approved: bool = False,
        create_parents: bool = True,
    ) -> dict[str, Any]:
        if not approved:
            return {"status": "APPROVAL_REQUIRED", "path": relative, "operation": "write_text"}
        target_path = self._path(relative)
        target = shlex.quote(str(target_path))
        encoded = base64.b64encode(content.encode("utf-8")).decode("ascii")
        parent = shlex.quote(str(target_path.parent))
        prefix = f"mkdir -p {parent} && " if create_parents else ""
        result = self._exec(f"{prefix}printf %s {shlex.quote(encoded)} | base64 -d > {target}")
        result.update({"path": relative, "bytes": len(content.encode('utf-8')), "approved": True})
        return result

    def run(
        self,
        argv: Sequence[str],
        *,
        cwd: str = ".",
        timeout: int = 300,
        approved: bool = False,
        read_only: bool = False,
    ) -> dict[str, Any]:
        if not argv:
            raise ValueError("remote command argv is required")
        if not read_only and not approved:
            return {
                "status": "APPROVAL_REQUIRED",
                "operation": "remote_command",
                "argv": list(argv),
                "cwd": cwd,
            }
        directory = shlex.quote(str(self._path(cwd)))
        rendered = " ".join(shlex.quote(str(item)) for item in argv)
        result = self._exec(f"cd {directory} && exec {rendered}", timeout=timeout)
        result.update({"argv": list(argv), "cwd": cwd, "approved": bool(approved), "read_only": bool(read_only)})
        return result
