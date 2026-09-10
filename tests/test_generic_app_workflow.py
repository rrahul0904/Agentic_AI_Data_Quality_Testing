from __future__ import annotations

import json

from fastapi.testclient import TestClient

from agentic_data_platform.api.app import create_app
from agentic_data_platform.apps import GenericAppWorkflow
from agentic_data_platform.cli import DOMAIN_CLI_TOOLS
from agentic_data_platform.tools.builtin import build_tool_registry


def test_python_scaffold_is_runnable_hash_bound_and_valid(tmp_path):
    workflow = GenericAppWorkflow(tmp_path)
    plan = workflow.scaffold_plan(
        app_name="reservation-ops",
        directory="apps/reservation-ops",
        framework="python-http",
        title="Reservation Ops",
        port=8080,
    )

    assert plan["status"] == "PASS"
    assert plan["framework"] == "python-http"
    assert {"app.py", "requirements.txt", "Dockerfile"} <= set(plan["files"])
    assert "/healthz" == plan["health_path"]
    assert workflow.validate(plan)["status"] == "PASS"

    applied = workflow.scaffold_apply(
        plan,
        approval_fingerprint=plan["approval_fingerprint"],
    )
    assert applied["status"] == "PASS"
    assert applied["verified"] is True
    assert (tmp_path / "apps/reservation-ops/app.py").is_file()


def test_node_and_static_templates_are_supported(tmp_path):
    workflow = GenericAppWorkflow(tmp_path)
    node = workflow.scaffold_plan(
        app_name="node-ui",
        directory="apps/node-ui",
        framework="node-http",
    )
    static = workflow.scaffold_plan(
        app_name="docs",
        directory="apps/docs",
        framework="static",
    )

    assert json.loads(node["files"]["package.json"])["scripts"]["start"] == "node server.js"
    assert "index.html" in static["files"]
    assert "nginx.conf" in static["files"]
    assert "listen 8080;" in static["files"]["nginx.conf"]
    assert "USER nginx" in static["files"]["Dockerfile"]
    assert node["approval_fingerprint"] != static["approval_fingerprint"]


def test_scaffold_apply_recomputes_fingerprint_and_blocks_tampering(tmp_path):
    workflow = GenericAppWorkflow(tmp_path)
    plan = workflow.scaffold_plan(
        app_name="portal",
        directory="portal",
        framework="python-http",
    )
    approved = plan["approval_fingerprint"]
    plan["files"]["app.py"] += "\n# late change\n"

    result = workflow.scaffold_apply(plan, approval_fingerprint=approved)

    assert result["status"] == "STALE_APPROVAL"
    assert not (tmp_path / "portal/app.py").exists()


def test_preview_plan_is_loopback_only_and_resource_bounded(tmp_path):
    workflow = GenericAppWorkflow(tmp_path)
    scaffold = workflow.scaffold_plan(
        app_name="portal",
        directory="portal",
        framework="python-http",
        port=8080,
    )
    preview = workflow.preview_plan(
        scaffold,
        host_port=18080,
        memory_mb=768,
        cpus=1.5,
    )

    assert preview["preview_url"] == "http://127.0.0.1:18080/"
    assert preview["health_url"] == "http://127.0.0.1:18080/healthz"
    assert preview["memory_mb"] == 768
    assert preview["cpus"] == 1.5
    assert preview["approval_fingerprint"]


def test_preview_fails_closed_without_docker(tmp_path, monkeypatch):
    workflow = GenericAppWorkflow(tmp_path)
    scaffold = workflow.scaffold_plan(
        app_name="portal",
        directory="portal",
        framework="python-http",
    )
    preview = workflow.preview_plan(scaffold)
    monkeypatch.setattr("agentic_data_platform.apps.generic.shutil.which", lambda _: None)

    result = GenericAppWorkflow.preview_run(
        preview,
        approval_fingerprint=preview["approval_fingerprint"],
    )

    assert result["status"] == "BLOCKED_UNAVAILABLE"
    assert "Docker is required" in result["reason"]


def test_preview_stale_approval_does_not_execute(tmp_path):
    workflow = GenericAppWorkflow(tmp_path)
    scaffold = workflow.scaffold_plan(
        app_name="portal",
        directory="portal",
        framework="python-http",
    )
    preview = workflow.preview_plan(scaffold)

    result = GenericAppWorkflow.preview_run(
        preview,
        approval_fingerprint="wrong",
    )

    assert result["status"] == "STALE_APPROVAL"


def test_kubernetes_deployment_plan_is_nonroot_readonly_and_resource_bounded(tmp_path):
    workflow = GenericAppWorkflow(tmp_path)
    scaffold = workflow.scaffold_plan(
        app_name="portal",
        directory="portal",
        framework="python-http",
        port=8080,
    )
    deploy = workflow.deployment_plan(
        scaffold,
        backend="kubernetes",
        image="example/portal:sha",
        namespace="ade",
        replicas=3,
    )

    manifest = deploy["manifest"]
    deployment, service = manifest["items"]
    container = deployment["spec"]["template"]["spec"]["containers"][0]
    assert deploy["backend"] == "kubernetes"
    assert manifest["kind"] == "List"
    assert deployment["metadata"]["namespace"] == "ade"
    assert deployment["spec"]["replicas"] == 3
    assert service["kind"] == "Service"
    assert service["spec"]["ports"][0]["targetPort"] == 8080
    assert container["securityContext"]["allowPrivilegeEscalation"] is False
    assert container["securityContext"]["readOnlyRootFilesystem"] is True
    assert container["securityContext"]["runAsNonRoot"] is True
    assert container["securityContext"]["capabilities"]["drop"] == ["ALL"]
    assert container["readinessProbe"]["httpGet"]["path"] == "/healthz"
    assert container["resources"]["limits"]["memory"] == "512Mi"
    assert deploy["approval_fingerprint"]


def test_docker_deployment_plan_contains_real_run_and_health_contract(tmp_path):
    workflow = GenericAppWorkflow(tmp_path)
    scaffold = workflow.scaffold_plan(
        app_name="portal",
        directory="portal",
        framework="python-http",
        port=8080,
    )
    deploy = workflow.deployment_plan(
        scaffold,
        backend="docker",
        image="example/portal:sha",
        host_port=18081,
    )

    assert deploy["host_port"] == 18081
    assert deploy["container_port"] == 8080
    assert deploy["deployment_url"] == "http://127.0.0.1:18081/"
    assert deploy["health_url"] == "http://127.0.0.1:18081/healthz"
    assert deploy["security"]["root_filesystem_read_only"] is True
    assert deploy["security"]["capabilities_dropped"] == "ALL"
    assert deploy["security"]["loopback_only"] is True


def test_docker_deployment_run_builds_and_starts_hardened_container(tmp_path, monkeypatch):
    workflow = GenericAppWorkflow(tmp_path)
    scaffold = workflow.scaffold_plan(
        app_name="portal",
        directory="portal",
        framework="python-http",
        port=8080,
    )
    deploy = workflow.deployment_plan(
        scaffold,
        backend="docker",
        image="example/portal:sha",
        host_port=18081,
    )
    calls = []

    class Result:
        def __init__(self, returncode=0, stdout="", stderr=""):
            self.returncode = returncode
            self.stdout = stdout
            self.stderr = stderr

    def fake_run(command, **kwargs):
        calls.append((list(command), kwargs))
        if "run" in command:
            return Result(stdout="container-123\n")
        return Result(stdout="ok\n")

    monkeypatch.setattr("agentic_data_platform.apps.generic.shutil.which", lambda _: "/usr/bin/docker")
    monkeypatch.setattr("agentic_data_platform.apps.generic.subprocess.run", fake_run)

    result = GenericAppWorkflow.deployment_run(
        deploy,
        approval_fingerprint=deploy["approval_fingerprint"],
    )

    assert result["status"] == "PASS"
    assert result["phase"] == "deployed"
    run_command = next(command for command, _ in calls if "run" in command)
    assert "--read-only" in run_command
    assert ["--cap-drop", "ALL"] == run_command[run_command.index("--cap-drop"):run_command.index("--cap-drop") + 2]
    assert "127.0.0.1:18081:8080" in run_command
    assert result["container_id"] == "container-123"


def test_deployment_execution_fails_closed_when_backend_cli_missing(tmp_path, monkeypatch):
    workflow = GenericAppWorkflow(tmp_path)
    scaffold = workflow.scaffold_plan(
        app_name="portal",
        directory="portal",
        framework="node-http",
    )
    docker = workflow.deployment_plan(scaffold, backend="docker")
    kube = workflow.deployment_plan(scaffold, backend="kubernetes")
    monkeypatch.setattr("agentic_data_platform.apps.generic.shutil.which", lambda _: None)

    assert GenericAppWorkflow.deployment_run(
        docker,
        approval_fingerprint=docker["approval_fingerprint"],
    )["status"] == "BLOCKED_UNAVAILABLE"
    assert GenericAppWorkflow.deployment_run(
        kube,
        approval_fingerprint=kube["approval_fingerprint"],
    )["status"] == "BLOCKED_UNAVAILABLE"


def test_rollback_plan_is_explicit_and_hash_bound(tmp_path):
    workflow = GenericAppWorkflow(tmp_path)
    scaffold = workflow.scaffold_plan(
        app_name="portal",
        directory="portal",
        framework="python-http",
    )
    kube = workflow.deployment_plan(
        scaffold,
        backend="kubernetes",
        namespace="ade",
    )
    rollback = GenericAppWorkflow.rollback_plan(kube)

    assert rollback["command"] == [
        "kubectl",
        "rollout",
        "undo",
        "deployment/portal",
        "-n",
        "ade",
    ]
    assert rollback["approval_fingerprint"]


def test_generic_app_tools_and_cli_api_surfaces_are_exposed():
    registry = build_tool_registry()
    names = {definition.name for definition in registry.definitions()}
    assert {
        "generic_app_scaffold_plan",
        "generic_app_scaffold_apply",
        "generic_app_validate",
        "generic_app_preview_plan",
        "generic_app_preview_run",
        "generic_app_verify_url",
        "generic_app_deployment_plan",
        "generic_app_deployment_run",
        "generic_app_rollback_plan",
        "generic_app_rollback_run",
    } <= names

    expected = {
        "plan",
        "validate",
        "apply",
        "deploy",
        "generic-scaffold-plan",
        "generic-scaffold-apply",
        "generic-validate",
        "generic-preview-plan",
        "generic-preview-run",
        "generic-verify-url",
        "generic-deployment-plan",
        "generic-deployment-run",
        "generic-rollback-plan",
        "generic-rollback-run",
    }
    assert set(DOMAIN_CLI_TOOLS["app"]) == expected

    client = TestClient(create_app())
    response = client.get("/api/v1/domains")
    assert response.status_code == 200
    assert set(response.json()["app"]) == expected
