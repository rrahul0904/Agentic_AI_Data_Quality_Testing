from __future__ import annotations

from fastapi.testclient import TestClient

from agentic_data_platform.api.app import create_app
from agentic_data_platform.cli import DOMAIN_CLI_TOOLS
from agentic_data_platform.connectors.snowflake import SnowflakeConfig, SnowflakeConnector
from agentic_data_platform.ml import (
    EmbeddedModelRegistryRuntime,
    SnowflakeModelRegistryAdapter,
    plan_log_model,
    plan_model_lifecycle,
)
from agentic_data_platform.snowflake import GovernedSnowflakeMutationExecutor


class ModelFixture:
    def __init__(self):
        self.versions = {"V1", "V2"}
        self.default = "V1"
        self.sql = []

    def __call__(self, sql):
        self.sql.append(sql)
        lowered = sql.casefold()
        if lowered.startswith("show models"):
            return {"rows": ({"name": "CHURN_MODEL"},)}
        if lowered.startswith("show versions in model"):
            return {"rows": tuple({"name": item} for item in sorted(self.versions))}
        if lowered.startswith("alter model") and "drop version" in lowered:
            version = sql.split()[-1].strip("'\"")
            self.versions.discard(version)
            return {"rows": (), "query_id": "q-drop-version"}
        if lowered.startswith("alter model") and "set default_version" in lowered:
            self.default = sql.rsplit("'", 2)[1]
            return {"rows": (), "query_id": "q-default"}
        if lowered.startswith("drop model"):
            return {"rows": (), "query_id": "q-drop-model"}
        raise AssertionError(sql)


def test_model_registry_inventory_and_versions():
    fixture = ModelFixture()
    connector = SnowflakeConnector(fixture, SnowflakeConfig(database="HOTEL", schema="ML"))
    adapter = SnowflakeModelRegistryAdapter(connector)

    assert adapter.models(database="HOTEL", schema="ML")[0]["name"] == "CHURN_MODEL"
    assert {item["name"] for item in adapter.versions("HOTEL.ML.CHURN_MODEL")} == {"V1", "V2"}


def test_model_log_plan_and_embedded_runtime_are_fingerprint_bound():
    plan = plan_log_model(
        model_name="CHURN_MODEL",
        version_name="V3",
        metrics={"auc": 0.91},
        pip_requirements=["scikit-learn==1.5.0"],
        python_version="3.11",
    )
    assert "registry.log_model" in plan["python"]
    assert plan["parameters"]["metrics"]["auc"] == 0.91

    class FakeRegistry:
        def __init__(self):
            self.calls = []
        def log_model(self, **kwargs):
            self.calls.append(kwargs)
            return "CHURN_MODEL:V3"

    registry = FakeRegistry()
    runtime = EmbeddedModelRegistryRuntime(registry)
    blocked = runtime.log_model(object(), plan, approval_fingerprint="wrong")
    assert blocked["status"] == "BLOCKED_APPROVAL"

    result = runtime.log_model(object(), plan, approval_fingerprint=plan["approval_fingerprint"])
    assert result["status"] == "PASS"
    assert registry.calls[0]["version_name"] == "V3"


def test_model_lifecycle_plans_capture_destructive_version_and_model_deletes():
    default = plan_model_lifecycle(
        action="set-default",
        model_name="HOTEL.ML.CHURN_MODEL",
        version_name="V2",
    )
    version = plan_model_lifecycle(
        action="drop-version",
        model_name="HOTEL.ML.CHURN_MODEL",
        version_name="V1",
    )
    model = plan_model_lifecycle(
        action="drop-model",
        model_name="HOTEL.ML.CHURN_MODEL",
    )

    assert default["destructive"] is False
    assert default["statement_type"] == "ALTER"
    assert version["destructive"] is True
    assert version["statement_type"] == "ALTER_MODEL_DROP_VERSION"
    assert model["destructive"] is True
    assert version["sql"].endswith("DROP VERSION V1")


def test_drop_model_version_executes_only_with_destructive_confirmation_and_verifies_absence():
    fixture = ModelFixture()
    connector = SnowflakeConnector(fixture, SnowflakeConfig(database="HOTEL", schema="ML"))
    executor = GovernedSnowflakeMutationExecutor(connector)
    plan = plan_model_lifecycle(
        action="drop-version",
        model_name="HOTEL.ML.CHURN_MODEL",
        version_name="V1",
    )

    blocked = executor.execute(
        plan["sql"],
        approval_fingerprint=plan["approval_fingerprint"],
        approved=True,
    )
    assert blocked["status"] == "BLOCKED_APPROVAL"
    assert "V1" in fixture.versions

    result = executor.execute(
        plan["sql"],
        approval_fingerprint=plan["approval_fingerprint"],
        approved=True,
        confirm_destructive=True,
    )
    assert result["status"] == "PASS"
    assert "V1" not in fixture.versions
    assert any(item["kind"] == "model_version_absence" and item["passed"] for item in result["verification"])


def test_ml_surfaces_exposed():
    assert set(DOMAIN_CLI_TOOLS["ml"]) == {
        "models", "versions", "log-plan", "workflow-plan", "lifecycle-plan", "lifecycle-execute"
    }
    client = TestClient(create_app())
    assert set(client.get("/api/v1/domains").json()["ml"]) == set(DOMAIN_CLI_TOOLS["ml"])
