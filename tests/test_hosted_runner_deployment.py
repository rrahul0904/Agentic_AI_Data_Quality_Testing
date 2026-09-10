from __future__ import annotations

from pathlib import Path

import yaml


def test_hosted_runner_container_deployment_is_persistent_and_policy_worker_based():
    dockerfile = Path("deploy/hosted-runner/Dockerfile").read_text()
    compose = yaml.safe_load(Path("deploy/hosted-runner/docker-compose.yml").read_text())

    assert "scripts/run_hosted_runner.py" in dockerfile
    assert 'VOLUME ["/data", "/workspace"]' in dockerfile
    assert "--database" in dockerfile
    assert "/data/hosted-runner.db" in dockerfile

    service = compose["services"]["ade-hosted-runner"]
    assert service["restart"] == "unless-stopped"
    assert "ade-runner-state:/data" in service["volumes"]
    assert "/data/hosted-runner.db" in service["command"]
    assert "--json" in service["command"]
    assert "ade-runner-state" in compose["volumes"]
