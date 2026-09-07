from __future__ import annotations

import json
import subprocess

from agentic_data_platform.connections.docker_discovery import discover_docker_connections
from agentic_data_platform.connections.ssh_tunnel import SSHTunnelManager, TunnelConfig


def test_docker_discovery_finds_supported_local_warehouses():
    def runner(argv):
        if argv[:2] == ["docker", "version"]:
            return subprocess.CompletedProcess(argv, 0, "27.0.1\n", "")
        if argv[:2] == ["docker", "ps"]:
            rows = [
                {
                    "Image": "postgres:16",
                    "Names": "hotel-postgres",
                    "Ports": "0.0.0.0:55432->5432/tcp",
                },
                {
                    "Image": "clickhouse/clickhouse-server:latest",
                    "Names": "analytics-clickhouse",
                    "Ports": "127.0.0.1:58123->8123/tcp",
                },
                {
                    "Image": "redis:latest",
                    "Names": "cache",
                    "Ports": "6379/tcp",
                },
            ]
            return subprocess.CompletedProcess(
                argv,
                0,
                "\n".join(json.dumps(item) for item in rows),
                "",
            )
        raise AssertionError(argv)

    result = discover_docker_connections(runner=runner)
    assert result["status"] == "PASS"
    assert result["count"] == 2
    by_platform = {item["platform"]: item for item in result["connections"]}
    assert by_platform["postgres"]["config"]["port"] == 55432
    assert by_platform["clickhouse"]["config"]["port"] == 58123


def test_docker_discovery_is_honest_when_daemon_unavailable():
    def runner(argv):
        return subprocess.CompletedProcess(argv, 1, "", "Cannot connect to Docker daemon")

    result = discover_docker_connections(runner=runner)
    assert result["status"] == "SKIP_EXTERNAL"
    assert result["connections"] == []


class FakeProcess:
    def __init__(self):
        self.pid = 12345
        self.stderr = None
        self.returncode = None
        self.terminated = False

    def poll(self):
        return self.returncode

    def terminate(self):
        self.terminated = True
        self.returncode = 0

    def wait(self, timeout=None):
        return self.returncode

    def kill(self):
        self.returncode = -9


def test_ssh_tunnel_command_lifecycle_uses_batch_key_auth():
    calls = []
    process = FakeProcess()

    def popen(argv, **kwargs):
        calls.append((argv, kwargs))
        return process

    manager = SSHTunnelManager(popen)
    config = TunnelConfig(
        ssh_host="bastion.example.com",
        ssh_user="data",
        remote_host="warehouse.internal",
        remote_port=5432,
        local_port=15432,
        identity_file="~/.ssh/id_ed25519",
    )
    started = manager.start("warehouse", config)
    assert started["status"] == "PASS"
    assert started["local_port"] == 15432
    command = calls[0][0]
    assert command[:2] == ["ssh", "-N"]
    assert "BatchMode=yes" in command
    assert "127.0.0.1:15432:warehouse.internal:5432" in command
    assert "data@bastion.example.com" == command[-1]

    status = manager.status("warehouse")
    assert status["running"] is True
    stopped = manager.stop("warehouse")
    assert stopped["stopped"] is True
    assert process.terminated is True
    assert manager.status("warehouse")["status"] == "NOT_FOUND"
