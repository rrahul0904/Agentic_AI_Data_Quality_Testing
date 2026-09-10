from __future__ import annotations

import json

import pytest
from fastapi.testclient import TestClient

from agentic_data_platform.api.app import create_app
from agentic_data_platform.cli import DOMAIN_CLI_TOOLS
from agentic_data_platform.ml import AgenticMLWorkflow, agentic_ml_plan
from agentic_data_platform.tools.builtin import build_tool_registry


def _regression_records():
    return [
        {"x": float(i), "target": float(2 * i + 3)}
        for i in range(1, 61)
    ]


def _classification_records():
    values = []
    for i in range(-30, 0):
        values.append({"x": float(i), "label": "NEG"})
    for i in range(1, 31):
        values.append({"x": float(i), "label": "POS"})
    return values


def test_regression_workflow_compares_models_selects_registers_and_verifies(tmp_path):
    plan = agentic_ml_plan(
        task="regression",
        source_id="fixture://linear",
        feature_columns=["x"],
        label_column="target",
        model_name="revenue_forecast",
        version="v1",
        train_fraction=0.75,
        seed=7,
    )
    result = AgenticMLWorkflow(tmp_path).run(
        plan,
        _regression_records(),
        approval_fingerprint=plan["approval_fingerprint"],
    )

    assert result["status"] == "PASS"
    assert result["selected_candidate"] == "linear_regression"
    by_candidate = {
        item["candidate"]: item["metrics"]
        for item in result["candidate_results"]
    }
    assert by_candidate["linear_regression"]["mae"] < by_candidate["mean_baseline"]["mae"]
    assert result["verification"]["status"] == "PASS"
    assert result["lineage"]["source"] == "fixture://linear"
    assert result["lineage"]["target"] == "revenue_forecast:v1"
    assert result["operation_estimate"]["estimated_local_cost_usd"] == 0.0
    assert result["artifact_fingerprint"]
    assert result["evidence_fingerprint"]

    path = tmp_path / result["registry_path"]
    artifact = json.loads(path.read_text())
    assert artifact["selected_candidate"] == "linear_regression"
    assert artifact["artifact_fingerprint"] == result["artifact_fingerprint"]


def test_classification_workflow_selects_nearest_centroid(tmp_path):
    plan = agentic_ml_plan(
        task="classification",
        source_id="fixture://binary",
        feature_columns=["x"],
        label_column="label",
        model_name="sign_classifier",
        version="v1",
        seed=11,
    )
    result = AgenticMLWorkflow(tmp_path).run(
        plan,
        _classification_records(),
        approval_fingerprint=plan["approval_fingerprint"],
    )

    assert result["status"] == "PASS"
    assert result["selected_candidate"] == "nearest_centroid"
    metrics = {
        item["candidate"]: item["metrics"]["accuracy"]
        for item in result["candidate_results"]
    }
    assert metrics["nearest_centroid"] > metrics["majority_baseline"]
    assert result["selected_metrics"]["accuracy"] == pytest.approx(1.0)


def test_agentic_ml_stale_approval_never_writes_artifact(tmp_path):
    plan = agentic_ml_plan(
        task="regression",
        source_id="fixture://linear",
        feature_columns=["x"],
        label_column="target",
        model_name="blocked_model",
        version="v1",
    )
    result = AgenticMLWorkflow(tmp_path).run(
        plan,
        _regression_records(),
        approval_fingerprint="tampered",
    )

    assert result["status"] == "STALE_APPROVAL"
    assert not (tmp_path / ".ade/ml/registry/blocked_model/v1.json").exists()


def test_agentic_ml_rejects_bad_rows_but_records_evidence(tmp_path):
    records = _regression_records()
    records.insert(4, {"x": "not-a-number", "target": 7})
    records.insert(8, {"x": 4, "target": None})
    plan = agentic_ml_plan(
        task="regression",
        source_id="fixture://dirty",
        feature_columns=["x"],
        label_column="target",
        model_name="dirty_model",
        version="v1",
    )
    result = AgenticMLWorkflow(tmp_path).run(
        plan,
        records,
        approval_fingerprint=plan["approval_fingerprint"],
    )

    assert result["status"] == "PASS"
    assert result["data_evidence"]["rows_rejected"] == 2
    assert len(result["rejected_rows"]) == 2
    assert result["data_evidence"]["data_fingerprint"]


def test_registered_artifact_supports_verified_inference(tmp_path):
    workflow = AgenticMLWorkflow(tmp_path)
    plan = agentic_ml_plan(
        task="regression",
        source_id="fixture://linear",
        feature_columns=["x"],
        label_column="target",
        model_name="predictor",
        version="v1",
    )
    workflow.run(
        plan,
        _regression_records(),
        approval_fingerprint=plan["approval_fingerprint"],
    )

    prediction = workflow.predict("predictor", "v1", {"x": 100.0})

    assert prediction["status"] == "PASS"
    assert prediction["prediction"] == pytest.approx(203.0, abs=1e-5)
    assert prediction["artifact_fingerprint"]
    assert prediction["inference_fingerprint"]


def test_tampered_registry_artifact_is_rejected(tmp_path):
    workflow = AgenticMLWorkflow(tmp_path)
    plan = agentic_ml_plan(
        task="classification",
        source_id="fixture://binary",
        feature_columns=["x"],
        label_column="label",
        model_name="tamper_check",
        version="v1",
    )
    workflow.run(
        plan,
        _classification_records(),
        approval_fingerprint=plan["approval_fingerprint"],
    )
    path = tmp_path / ".ade/ml/registry/tamper_check/v1.json"
    artifact = json.loads(path.read_text())
    artifact["model"]["centroids"]["NEG"][0] = 9999.0
    path.write_text(json.dumps(artifact))

    with pytest.raises(ValueError, match="fingerprint mismatch"):
        workflow.predict("tamper_check", "v1", {"x": -10})


def test_agentic_ml_plan_requires_competing_candidates_and_valid_fraction():
    with pytest.raises(ValueError, match="at least two"):
        agentic_ml_plan(
            task="regression",
            source_id="fixture://linear",
            feature_columns=["x"],
            label_column="target",
            model_name="bad",
            version="v1",
            candidates=["mean_baseline"],
        )
    with pytest.raises(ValueError, match="train_fraction"):
        agentic_ml_plan(
            task="classification",
            source_id="fixture://binary",
            feature_columns=["x"],
            label_column="label",
            model_name="bad",
            version="v1",
            train_fraction=0.2,
        )


def test_agentic_ml_tools_cli_and_api_are_exposed():
    registry = build_tool_registry()
    names = {definition.name for definition in registry.definitions()}
    assert {
        "agentic_ml_plan",
        "agentic_ml_run",
        "agentic_ml_predict",
        "agentic_ml_artifacts",
    } <= names

    expected = set(DOMAIN_CLI_TOOLS["ml"])
    assert {
        "agentic-plan",
        "agentic-run",
        "agentic-predict",
        "agentic-artifacts",
    } <= expected

    client = TestClient(create_app())
    response = client.get("/api/v1/domains")
    assert response.status_code == 200
    assert set(response.json()["ml"]) == expected
