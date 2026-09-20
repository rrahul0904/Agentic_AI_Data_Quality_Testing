from __future__ import annotations

from pathlib import Path

import yaml


ROOT = Path(__file__).resolve().parents[1]


def _yaml(path: str):
    return yaml.safe_load((ROOT / path).read_text())


def test_release_compose_uses_immutable_images_and_internal_api() -> None:
    payload = _yaml("docker-compose.release.yml")
    api = payload["services"]["api"]
    web = payload["services"]["web"]

    assert "build" not in api
    assert "build" not in web
    assert api["image"].startswith("${ADE_API_IMAGE:")
    assert web["image"].startswith("${ADE_WEB_IMAGE:")
    assert "ports" not in api
    assert api["environment"]["ADE_RUNTIME_MODE"] == "production"
    assert api["environment"]["ADE_DEMO_MODE"] == "false"
    assert api["environment"]["ADE_AUTH_MODE"] == "api_key"
    assert web["environment"]["ADE_WEB_AUTH_MODE"] == "basic"
    assert web["environment"]["ADE_API_URL"] == "http://api:8001"


def test_production_containers_are_non_root() -> None:
    api = (ROOT / "deploy/Dockerfile.api").read_text()
    web = (ROOT / "apps/web/Dockerfile").read_text()

    assert "useradd --system --uid 10001 --gid 10001" in api
    assert "\nUSER ade\n" in api
    assert "COPY --chown=node:node" in web
    assert "\nUSER node\n" in web


def test_kubernetes_api_is_internal_non_root_and_probeable() -> None:
    deployment = _yaml("deploy/k8s/base/api-deployment.yaml")
    pod = deployment["spec"]["template"]["spec"]
    container = pod["containers"][0]

    assert pod["securityContext"]["runAsNonRoot"] is True
    assert pod["securityContext"]["runAsUser"] == 10001
    assert pod["securityContext"]["seccompProfile"]["type"] == "RuntimeDefault"
    assert container["securityContext"]["allowPrivilegeEscalation"] is False
    assert container["securityContext"]["capabilities"]["drop"] == ["ALL"]
    assert container["readinessProbe"]["httpGet"]["path"] == "/healthz"
    assert container["livenessProbe"]["httpGet"]["path"] == "/healthz"

    services = list(yaml.safe_load_all((ROOT / "deploy/k8s/base/services.yaml").read_text()))
    api_service = next(item for item in services if item["metadata"]["name"] == "ade-api")
    assert api_service["spec"]["type"] == "ClusterIP"
    assert api_service["spec"]["ports"][0]["port"] == 8001


def test_kubernetes_web_has_replicas_auth_and_health_probes() -> None:
    deployment = _yaml("deploy/k8s/base/web-deployment.yaml")
    assert deployment["spec"]["replicas"] >= 2
    pod = deployment["spec"]["template"]["spec"]
    container = pod["containers"][0]

    assert pod["securityContext"]["runAsNonRoot"] is True
    assert container["securityContext"]["allowPrivilegeEscalation"] is False
    assert container["securityContext"]["capabilities"]["drop"] == ["ALL"]
    assert container["readinessProbe"]["httpGet"]["path"] == "/api/healthz"
    env = {item["name"]: item["value"] for item in container["env"]}
    assert env["ADE_API_URL"] == "http://ade-api:8001"
    assert env["ADE_WEB_AUTH_MODE"] == "basic"


def test_kubernetes_network_policy_limits_api_to_web_tier() -> None:
    policy = _yaml("deploy/k8s/base/networkpolicy.yaml")
    assert policy["spec"]["podSelector"]["matchLabels"]["app"] == "ade-api"
    ingress = policy["spec"]["ingress"][0]
    assert ingress["from"][0]["podSelector"]["matchLabels"]["app"] == "ade-web"
    assert ingress["ports"][0]["port"] == 8001


def test_release_workflow_is_exact_sha_and_attested() -> None:
    workflow = (ROOT / ".github/workflows/production-release.yml").read_text()

    assert 'test "${GITHUB_REF}" = "refs/heads/main"' in workflow
    assert "sha-${{ github.sha }}" in workflow
    assert "actions/attest-build-provenance@v2" in workflow
    assert "production-release.json" in workflow
    assert "make snowflake-pipeline-live-e2e" in workflow
