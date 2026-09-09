from __future__ import annotations

import pytest

from agentic_data_platform.ml import EmbeddedSnowparkMLWorkflowRuntime, plan_snowpark_ml_workflow


class FakeFrame:
    def __init__(self, name: str):
        self.name = name
        self.random_split_calls = []
        self.limit_calls = []

    def random_split(self, weights, seed):
        self.random_split_calls.append((list(weights), seed))
        return FakeFrame(self.name + "_train"), FakeFrame(self.name + "_test")

    def limit(self, count):
        self.limit_calls.append(count)
        return FakeFrame(self.name + "_sample")


class FakeSession:
    def __init__(self):
        self.tables = []
        self.frame = FakeFrame("source")

    def table(self, name):
        self.tables.append(name)
        return self.frame


class FakeModel:
    def __init__(self, **kwargs):
        self.kwargs = kwargs
        self.fit_calls = []
        self.predict_calls = []

    def fit(self, frame):
        self.fit_calls.append(frame.name)
        return self

    def predict(self, frame):
        self.predict_calls.append(frame.name)
        return FakeFrame("predictions")


class FakeRegistry:
    def __init__(self):
        self.calls = []

    def log_model(self, **kwargs):
        self.calls.append(kwargs)
        return "HOTEL.ML.CHURN_MODEL:V3"


def test_snowpark_ml_classification_plan_generates_train_evaluate_register_code():
    plan = plan_snowpark_ml_workflow(
        task="classification",
        training_table="HOTEL.FEATURES.CHURN_TRAINING",
        input_cols=["AGE", "SPEND", "STAYS"],
        label_col="CHURNED",
        output_col="PREDICTION",
        registry_database="HOTEL",
        registry_schema="ML",
        model_name="CHURN_MODEL",
        version_name="V3",
        model_params={"n_estimators": 25, "max_depth": 4},
    )

    assert plan["status"] == "PASS"
    assert plan["metric_name"] == "accuracy"
    assert "XGBClassifier" in plan["python"]
    assert "model.fit(train_df)" in plan["python"]
    assert "accuracy_score" in plan["python"]
    assert "registry.log_model" in plan["python"]
    assert plan["parameters"]["input_cols"] == ["AGE", "SPEND", "STAYS"]
    assert len(plan["approval_fingerprint"]) == 64


def test_snowpark_ml_regression_plan_uses_mean_squared_error():
    plan = plan_snowpark_ml_workflow(
        task="regression",
        training_table="HOTEL.FEATURES.REVENUE_TRAINING",
        input_cols=["OCCUPANCY", "ADR"],
        label_col="REVENUE",
        output_col="PREDICTED_REVENUE",
        registry_database="HOTEL",
        registry_schema="ML",
        model_name="REVENUE_MODEL",
        version_name="V1",
    )
    assert plan["metric_name"] == "mean_squared_error"
    assert "XGBRegressor" in plan["python"]
    assert "mean_squared_error" in plan["python"]


def test_snowpark_ml_embedded_runtime_trains_evaluates_and_registers():
    plan = plan_snowpark_ml_workflow(
        task="classification",
        training_table="HOTEL.FEATURES.CHURN_TRAINING",
        input_cols=["AGE", "SPEND"],
        label_col="CHURNED",
        output_col="PREDICTION",
        registry_database="HOTEL",
        registry_schema="ML",
        model_name="CHURN_MODEL",
        version_name="V3",
        train_fraction=0.75,
        seed=7,
        model_params={"n_estimators": 10},
    )
    session = FakeSession()
    registry = FakeRegistry()
    models = []

    def factory(**kwargs):
        model = FakeModel(**kwargs)
        models.append(model)
        return model

    metric_calls = []

    def metric(**kwargs):
        metric_calls.append(kwargs)
        return 0.875

    runtime = EmbeddedSnowparkMLWorkflowRuntime(
        session=session,
        registry=registry,
        estimator_factory=factory,
        metric_function=metric,
    )

    blocked = runtime.run(plan, approval_fingerprint="wrong")
    assert blocked["status"] == "BLOCKED_APPROVAL"
    assert session.tables == []

    result = runtime.run(plan, approval_fingerprint=plan["approval_fingerprint"])

    assert result["status"] == "PASS"
    assert result["metric_value"] == 0.875
    assert result["model_name"] == "CHURN_MODEL"
    assert session.tables == ["HOTEL.FEATURES.CHURN_TRAINING"]
    assert session.frame.random_split_calls == [([0.75, 0.25], 7)]
    assert models[0].fit_calls == ["source_train"]
    assert models[0].predict_calls == ["source_test"]
    assert metric_calls[0]["y_true_col_names"] == ["CHURNED"]
    assert registry.calls[0]["metrics"] == {"accuracy": 0.875}
    assert registry.calls[0]["sample_input_data"].name == "source_train_sample"


def test_snowpark_ml_plan_rejects_unsafe_identifiers_and_invalid_train_fraction():
    base = dict(
        task="classification",
        training_table="HOTEL.FEATURES.CHURN_TRAINING",
        input_cols=["AGE"],
        label_col="CHURNED",
        output_col="PREDICTION",
        registry_database="HOTEL",
        registry_schema="ML",
        model_name="CHURN_MODEL",
        version_name="V1",
    )
    with pytest.raises(ValueError, match="qualified"):
        plan_snowpark_ml_workflow(**{**base, "training_table": "HOTEL.FEATURES.X; DROP TABLE Y"})
    with pytest.raises(ValueError, match="train_fraction"):
        plan_snowpark_ml_workflow(**{**base, "train_fraction": 1.0})
