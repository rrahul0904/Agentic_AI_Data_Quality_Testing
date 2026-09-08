"""Managed SSH local-forward tunnels using the system ssh client."""

from __future__ import annotations

import socket
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable


PopenFactory = Callable[..., subprocess.Popen[Any]]


def _free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])


@dataclass(frozen=True)
class TunnelConfig:
    ssh_host: str
    ssh_user: str
    remote_host: str
    remote_port: int
    ssh_port: int = 22
    local_port: int | None = None
    identity_file: str | None = None


class SSHTunnelManager:
    def __init__(self, popen_factory: PopenFactory | None = None) -> None:
        self._popen = popen_factory or subprocess.Popen
        self._processes: dict[str, tuple[subprocess.Popen[Any], TunnelConfig, int]] = {}

    def command(self, config: TunnelConfig, local_port: int) -> list[str]:
        if not config.ssh_host.strip() or not config.ssh_user.strip():
            raise ValueError("ssh_host and ssh_user are required")
        if not config.remote_host.strip() or int(config.remote_port) <= 0:
            raise ValueError("remote_host and remote_port are required")
        command = [
            "ssh",
            "-N",
            "-o",
            "ExitOnForwardFailure=yes",
            "-o",
            "BatchMode=yes",
            "-p",
            str(int(config.ssh_port)),
            "-L",
            f"127.0.0.1:{local_port}:{config.remote_host}:{int(config.remote_port)}",
        ]
        if config.identity_file:
            identity = Path(config.identity_file).expanduser().resolve()
            command += ["-i", str(identity)]
        command.append(f"{config.ssh_user}@{config.ssh_host}")
        return command

    def start(self, name: str, config: TunnelConfig) -> dict[str, Any]:
        if name in self._processes and self._processes[name][0].poll() is None:
            return self.status(name)
        local_port = int(config.local_port or _free_port())
        command = self.command(config, local_port)
        try:
            process = self._popen(
                command,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.PIPE,
                text=True,
            )
        except FileNotFoundError:
            return {
                "status": "SKIP_EXTERNAL",
                "name": name,
                "reason": "ssh client is not installed",
            }
        self._processes[name] = (process, config, local_port)
        if process.poll() is not None:
            error = ""
            if process.stderr is not None:
                error = process.stderr.read()[-2000:]
            self._processes.pop(name, None)
            return {
                "status": "FAIL",
                "name": name,
                "reason": error or "ssh tunnel exited during startup",
            }
        return {
            "status": "PASS",
            "name": name,
            "local_host": "127.0.0.1",
            "local_port": local_port,
            "remote_host": config.remote_host,
            "remote_port": int(config.remote_port),
            "pid": process.pid,
        }

    def status(self, name: str) -> dict[str, Any]:
        item = self._processes.get(name)
        if item is None:
            return {"status": "NOT_FOUND", "name": name}
        process, config, local_port = item
        running = process.poll() is None
        return {
            "status": "PASS" if running else "STOPPED",
            "name": name,
            "running": running,
            "local_host": "127.0.0.1",
            "local_port": local_port,
            "remote_host": config.remote_host,
            "remote_port": int(config.remote_port),
            "pid": process.pid,
        }

    def stop(self, name: str) -> dict[str, Any]:
        item = self._processes.pop(name, None)
        if item is None:
            return {"status": "NOT_FOUND", "name": name}
        process, _, _ = item
        if process.poll() is None:
            process.terminate()
            try:
                process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait(timeout=5)
        return {"status": "PASS", "name": name, "stopped": True}
