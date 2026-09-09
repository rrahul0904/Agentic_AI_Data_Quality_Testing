from __future__ import annotations

import json
import shutil
import subprocess

import pytest
import yaml
from fastapi.testclient import TestClient

from agentic_data_platform.api.app import create_app
from agentic_data_platform.apps import SnowflakeAppBuilder
from agentic_data_platform.cli import DOMAIN_CLI_TOOLS


def test_streamlit_builder_creates_current_definition_v2_project(tmp_path):
    builder = SnowflakeAppBuilder(tmp_path)
    plan = builder.plan(
        kind="streamlit",
        app_name="reservation_ops",
        directory="apps/reservation_ops",
        database="HOTEL",
        schema="APPS",
        query_warehouse="APP_WH",
        title="Reservation Ops",
        compute_pool="APP_POOL",
    )
    manifest = yaml.safe_load(plan["files"]["snowflake.yml"])
    entity = manifest["entities"]["reservation_ops"]

    assert manifest["definition_version"] == 2
    assert entity["type"] == "streamlit"
    assert entity["runtime_name"] == "SYSTEM$ST_CONTAINER_RUNTIME_PY3_11"
    assert entity["compute_pool"] == "APP_POOL"
    assert SnowflakeAppBuilder.validate(plan)["status"] == "PASS"

    result = builder.apply(plan, approval_fingerprint=plan["approval_fingerprint"])
    assert result["status"] == "PASS"
    assert (tmp_path / "apps/reservation_ops/streamlit_app.py").is_file()


def test_app_runtime_builder_creates_runnable_version_2_project(tmp_path):
    builder = SnowflakeAppBuilder(tmp_path)
    plan = builder.plan(
        kind="app-runtime",
        app_name="ade_portal",
        directory="apps/ade_portal",
        database="APPS",
        schema="PUBLIC",
        query_warehouse="APP_WH",
        title="ADE Portal",
    )
    manifest = yaml.safe_load(plan["files"]["app.yml"])
    assert manifest["version"] == 2
    assert manifest["name"] == "ade_portal"
    assert manifest["database"] == "APPS"
    assert manifest["run"]["command"] == ["node", "server.js"]
    assert SnowflakeAppBuilder.validate(plan)["status"] == "PASS"

    result = builder.apply(plan, approval_fingerprint=plan["approval_fingerprint"])
    assert result["verified"] is True
    assert json.loads((tmp_path / "apps/ade_portal/package.json").read_text())["scripts"]["start"] == "node server.js"

    if shutil.which("node"):
        checked = subprocess.run(
            ["node", "--check", "server.js"],
            cwd=tmp_path / "apps/ade_portal",
            capture_output=True,
            text=True,
            check=False,
        )
        assert checked.returncode == 0, checked.stderr


def test_app_apply_recomputes_plan_fingerprint_and_blocks_tampering(tmp_path):
    builder = SnowflakeAppBuilder(tmp_path)
    plan = builder.plan(
        kind="app-runtime",
        app_name="ade_portal",
        directory="apps/ade_portal",
        database="APPS",
        schema="PUBLIC",
        query_warehouse="APP_WH",
    )
    original = plan["approval_fingerprint"]
    plan["files"]["server.js"] += "\n// malicious late rewrite\n"
    result = builder.apply(plan, approval_fingerprint=original)
    assert result["status"] == "BLOCKED_APPROVAL"
    assert not (tmp_path / "apps/ade_portal/server.js").exists()


def test_app_deploy_is_honest_when_snowflake_cli_absent(tmp_path, monkeypatch):
    plan = SnowflakeAppBuilder(tmp_path).plan(
        kind="app-runtime",
        app_name="ade_portal",
        directory="apps/ade_portal",
        database="APPS",
        schema="PUBLIC",
        query_warehouse="APP_WH",
    )
    monkeypatch.setattr("agentic_data_platform.apps.builder.shutil.which", lambda _: None)
    result = SnowflakeAppBuilder.deploy(plan)
    assert result["status"] == "SKIP_EXTERNAL"
    assert result["command"] == ["snow", "app", "deploy"]


def test_app_surfaces_exposed():
    assert set(DOMAIN_CLI_TOOLS["app"]) == {"plan", "validate", "apply", "deploy"}
    client = TestClient(create_app())
    assert set(client.get("/api/v1/domains").json()["app"]) == {"plan", "validate", "apply", "deploy"}
