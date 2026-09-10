"""Snowpark ML train, evaluate, and register workflow."""

from __future__ import annotations

from hashlib import sha256
import json
import re
from typing import Any, Callable


_IDENTIFIER = re.compile(r"^[A-Za-z_][A-Za-z0-9_$]*$")


def _identifier(value: str) -> str:
    text = str(value).strip()
    if not _IDENTIFIER.fullmatch(text):
        raise ValueError(f"invalid Snowpark identifier: {text}")
    return text


def _qualified(value: str) -> str:
    parts = [part.strip() for part in str(value).split(".") if part.strip()]
    if not parts or any(not _IDENTIFIER.fullmatch(part) for part in parts):
        raise ValueError(f"invalid qualified Snowflake identifier: {value}")
    return ".".join(parts)


def plan_snowpark_ml_workflow(
    *,
    task: str,
    training_table: str,
    input_cols: list[str],
    label_col: str,
    output_col: str,
    registry_database: str,
    registry_schema: str,
    model_name: str,
    version_name: str,
    train_fraction: float = 0.8,
    seed: int = 42,
    model_params: dict[str, Any] | None = None,
    comment: str | None = None,
) -> dict[str, Any]:
    task = str(task).casefold()
    if task not in {"classification", "regression"}:
        raise ValueError("task must be classification or regression")
    if not input_cols:
        raise ValueError("input_cols must contain at least one feature")
    if not 0.05 <= float(train_fraction) <= 0.95:
        raise ValueError("train_fraction must be between 0.05 and 0.95")

    payload = {
        "task": task,
        "training_table": _qualified(training_table),
        "input_cols": [_identifier(item) for item in input_cols],
        "label_col": _identifier(label_col),
        "output_col": _identifier(output_col),
        "registry_database": _identifier(registry_database),
        "registry_schema": _identifier(registry_schema),
        "model_name": _identifier(model_name),
        "version_name": _identifier(version_name),
        "train_fraction": float(train_fraction),
        "seed": int(seed),
        "model_params": dict(model_params or {}),
        "comment": comment,
    }
    approval = sha256(json.dumps(payload, sort_keys=True, default=str).encode("utf-8")).hexdigest()
    estimator = "XGBClassifier" if task == "classification" else "XGBRegressor"
    metric_import = "accuracy_score" if task == "classification" else "mean_squared_error"
    metric_name = "accuracy" if task == "classification" else "mean_squared_error"

    code = "\n".join([
        "from snowflake.ml.modeling.xgboost import " + estimator,
        "from snowflake.ml.modeling.metrics import " + metric_import,
        "from snowflake.ml.registry import Registry",
        "",
        "source = session.table(" + repr(payload["training_table"]) + ")",
        "train_df, test_df = source.random_split([" + str(payload["train_fraction"]) + ", " + str(1.0 - payload["train_fraction"]) + "], seed=" + str(payload["seed"]) + ")",
        "model = " + estimator + "(",
        "    input_cols=" + repr(payload["input_cols"]) + ",",
        "    label_cols=[" + repr(payload["label_col"]) + "],",
        "    output_cols=[" + repr(payload["output_col"]) + "],",
        "    **" + repr(payload["model_params"]) + ",",
        ")",
        "model.fit(train_df)",
        "predictions = model.predict(test_df)",
        "score = " + metric_import + "(df=predictions, y_true_col_names=[" + repr(payload["label_col"]) + "], y_pred_col_names=[" + repr(payload["output_col"]) + "])",
        "registry = Registry(session=session, database_name=" + repr(payload["registry_database"]) + ", schema_name=" + repr(payload["registry_schema"]) + ")",
        "model_version = registry.log_model(",
        "    model=model,",
        "    model_name=" + repr(payload["model_name"]) + ",",
        "    version_name=" + repr(payload["version_name"]) + ",",
        "    comment=" + repr(payload["comment"]) + ",",
        "    metrics={" + repr(metric_name) + ": float(score)},",
        "    sample_input_data=train_df.limit(100),",
        ")",
    ]) + "\n"

    return {
        "status": "PASS",
        "mode": "SNOWPARK_ML_WORKFLOW_PLAN",
        "approval_fingerprint": approval,
        "parameters": payload,
        "metric_name": metric_name,
        "lineage": {
            "source": payload["training_table"],
            "target": f"{payload['registry_database']}.{payload['registry_schema']}.{payload['model_name']}:{payload['version_name']}",
            "features": payload["input_cols"],
            "label": payload["label_col"],
            "prediction": payload["output_col"],
        },
        "python": code,
    }


class EmbeddedSnowparkMLWorkflowRuntime:
    """Execute the workflow inside a process that already owns Snowpark objects."""

    def __init__(
        self,
        *,
        session: Any,
        registry: Any,
        estimator_factory: Callable[..., Any],
        metric_function: Callable[..., Any],
    ) -> None:
        self.session = session
        self.registry = registry
        self.estimator_factory = estimator_factory
        self.metric_function = metric_function

    def run(
        self,
        plan: dict[str, Any],
        *,
        approval_fingerprint: str,
    ) -> dict[str, Any]:
        expected = str(plan.get("approval_fingerprint") or "")
        if approval_fingerprint != expected:
            return {"status": "BLOCKED_APPROVAL", "reason": "Snowpark ML workflow fingerprint mismatch"}
        params = dict(plan.get("parameters") or {})
        source = self.session.table(params["training_table"])
        train_df, test_df = source.random_split(
            [params["train_fraction"], 1.0 - params["train_fraction"]],
            seed=params["seed"],
        )
        model = self.estimator_factory(
            input_cols=params["input_cols"],
            label_cols=[params["label_col"]],
            output_cols=[params["output_col"]],
            **params["model_params"],
        )
        model.fit(train_df)
        predictions = model.predict(test_df)
        score = self.metric_function(
            df=predictions,
            y_true_col_names=[params["label_col"]],
            y_pred_col_names=[params["output_col"]],
        )
        model_version = self.registry.log_model(
            model=model,
            model_name=params["model_name"],
            version_name=params["version_name"],
            comment=params["comment"],
            metrics={plan["metric_name"]: float(score)},
            sample_input_data=train_df.limit(100),
        )
        return {
            "status": "PASS",
            "task": params["task"],
            "training_table": params["training_table"],
            "metric_name": plan["metric_name"],
            "metric_value": float(score),
            "model_name": params["model_name"],
            "version_name": params["version_name"],
            "model_version": str(model_version),
            "lineage": dict(plan["lineage"]),
        }
