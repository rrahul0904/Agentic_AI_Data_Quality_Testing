"""Docker-based local warehouse discovery."""

from __future__ import annotations

import json
import re
import subprocess
from typing import Any, Callable


Runner = Callable[[list[str]], subprocess.CompletedProcess[str]]
_PORT = re.compile(r"(?:(?:0\.0\.0\.0|127\.0\.0\.1|\[::\]):)?(\d+)->(\d+)/(?:tcp|udp)")


def _run(argv: list[str]) -> subprocess.CompletedProcess[str]:
    return subprocess.run(argv, capture_output=True, text=True, check=False)


def _platform(image: str, name: str) -> tuple[str | None, int | None]:
    value = f"{image} {name}".casefold()
    rules = (
        ("postgres", "postgres", 5432),
        ("redshift", "redshift", 5439),
        ("mysql", "mysql", 3306),
        ("mariadb", "mysql", 3306),
        ("clickhouse", "clickhouse", 8123),
        ("trino", "trino", 8080),
        ("oracle", "oracle", 1521),
        ("mssql", "sqlserver", 1433),
        ("sqlserver", "sqlserver", 1433),
        ("duckdb", "duckdb", None),
    )
    for token, platform, default_port in rules:
        if token in value:
            return platform, default_port
    return None, None


def discover_docker_connections(
    *,
    runner: Runner | None = None,
) -> dict[str, Any]:
    run = runner or _run
    try:
        version = run(["docker", "version", "--format", "{{.Server.Version}}"])
    except FileNotFoundError:
        return {
            "status": "SKIP_EXTERNAL",
            "reason": "docker CLI is not installed",
            "connections": [],
        }
    if version.returncode != 0:
        return {
            "status": "SKIP_EXTERNAL",
            "reason": (version.stderr or version.stdout or "Docker daemon unavailable").strip(),
            "connections": [],
        }

    listing = run(["docker", "ps", "--format", "{{json .}}"])
    if listing.returncode != 0:
        return {
            "status": "SKIP_EXTERNAL",
            "reason": (listing.stderr or listing.stdout or "docker ps failed").strip(),
            "connections": [],
        }

    connections = []
    for line in listing.stdout.splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            item = json.loads(line)
        except json.JSONDecodeError:
            continue
        image = str(item.get("Image") or "")
        name = str(item.get("Names") or item.get("Name") or "")
        platform, default_port = _platform(image, name)
        if platform is None:
            continue
        host_port = None
        container_port = None
        for match in _PORT.finditer(str(item.get("Ports") or "")):
            candidate_host = int(match.group(1))
            candidate_container = int(match.group(2))
            if default_port is None or candidate_container == default_port:
                host_port = candidate_host
                container_port = candidate_container
                break
        config: dict[str, Any] = {"host": "127.0.0.1"}
        if host_port is not None:
            config["port"] = host_port
        connections.append(
            {
                "name": f"docker-{name or platform}",
                "platform": platform,
                "source": "docker",
                "container": name,
                "image": image,
                "container_port": container_port,
                "config": config,
                "credentials_required": platform not in {"duckdb"},
            }
        )
    return {
        "status": "PASS",
        "docker_server_version": version.stdout.strip(),
        "connections": connections,
        "count": len(connections),
    }
