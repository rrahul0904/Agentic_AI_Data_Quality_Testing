from __future__ import annotations

from pathlib import Path

from fastapi.testclient import TestClient

from agentic_data_platform.api.app import create_app
from agentic_data_platform.cli import DOMAIN_CLI_TOOLS


ROOT = Path(__file__).resolve().parents[1]
PAGE = ROOT / "apps" / "web" / "app" / "page.tsx"
WORKBENCH = ROOT / "apps" / "web" / "app" / "CapabilityWorkbench.tsx"
CERTIFICATION = ROOT / "apps" / "web" / "app" / "CertificationConsole.tsx"
CERTIFICATION_PAGE = ROOT / "apps" / "web" / "app" / "certification" / "page.tsx"


def test_operator_console_uses_same_governed_domain_contract_as_cli():
    client = TestClient(create_app())
    response = client.get("/api/v1/domains")
    assert response.status_code == 200
    api_domains = response.json()

    required = {
        "semantic",
        "cortex-agent",
        "teams",
        "runner",
        "notebook",
        "browser",
        "app",
        "ml",
        "ai-workflow",
        "ide",
        "rules",
        "memory",
        "jobs",
        "automations",
        "advanced",
    }
    assert required <= set(api_domains)
    for domain in required & set(DOMAIN_CLI_TOOLS):
        assert set(api_domains[domain]) == set(DOMAIN_CLI_TOOLS[domain])


def test_workbench_sends_actor_interaction_environment_dry_run_and_approval():
    source = WORKBENCH.read_text(encoding="utf-8")

    assert 'const [actorMode, setActorMode]' in source
    assert 'const [interactionMode, setInteractionMode]' in source
    assert 'const [environment, setEnvironment]' in source
    assert "actor_mode: actorMode" in source
    assert "interaction_mode: interactionMode" in source
    assert "environment," in source
    assert "dry_run: dryRun" in source
    assert "approved," in source
    for mode in ("agent", "plan", "ask", "edit", "code"):
        assert f'<option value="{mode}">' in source


def test_operator_navigation_exposes_first_class_coco_workflows():
    source = PAGE.read_text(encoding="utf-8")
    for label in (
        "Investigations",
        "Agent",
        "Semantic Layer",
        "Teams",
        "Hosted Runner",
        "Notebooks",
        "Browser",
        "Apps",
        "ML Registry",
        "Desktop / IDE",
        "Rules & Context",
        "Advanced Workbench",
        "Sessions",
        "Runs / Evidence",
    ):
        assert f'"{label}"' in source

    for domain in (
        'domain="teams"',
        'domain="runner"',
        'domain="app"',
        'domain="ml"',
        'domain="ide"',
        'domain="advanced"',
    ):
        assert domain in source


def test_certification_control_room_is_routable_and_truthful():
    console = CERTIFICATION.read_text(encoding="utf-8")
    route = CERTIFICATION_PAGE.read_text(encoding="utf-8")

    assert "/api/v1/certification/coco" in console
    assert "Implementation incomplete" in console
    assert "Exact-head CI not evidenced here" in console
    assert "Live external not certified" in console
    assert "Superiority not certified" in console
    assert "unresolved_coco_capabilities" in console
    assert "golden_scenario_definitions" in console
    assert "<CertificationConsole />" in route


def test_certification_endpoint_never_claims_live_or_superiority_from_local_state():
    response = TestClient(create_app()).get("/api/v1/certification/coco")
    assert response.status_code == 200
    claims = response.json()["claims"]
    assert claims["live_external_certified"] is False
    assert claims["superiority_certified"] is False
