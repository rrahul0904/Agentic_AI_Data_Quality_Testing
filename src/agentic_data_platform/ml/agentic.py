"""Portable end-to-end agentic ML workflow with deterministic evidence."""

from __future__ import annotations

from hashlib import sha256
import json
import math
from pathlib import Path
import random
from typing import Any, Iterable, Mapping


def _digest(value: Any) -> str:
    return sha256(
        json.dumps(value, sort_keys=True, separators=(",", ":"), default=str).encode("utf-8")
    ).hexdigest()


def _name(value: str, field: str) -> str:
    text = "".join(ch for ch in str(value) if ch.isalnum() or ch in {"_", "-", "."}).strip(".-_")
    if not text:
        raise ValueError(f"{field} is required")
    return text[:128]


def _float(value: Any, field: str) -> float:
    try:
        result = float(value)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{field} must be numeric") from exc
    if not math.isfinite(result):
        raise ValueError(f"{field} must be finite")
    return result


def _solve_linear_system(matrix: list[list[float]], vector: list[float]) -> list[float]:
    size = len(vector)
    augmented = [list(matrix[row]) + [float(vector[row])] for row in range(size)]
    for col in range(size):
        pivot = max(range(col, size), key=lambda row: abs(augmented[row][col]))
        if abs(augmented[pivot][col]) < 1e-12:
            raise ValueError("singular design matrix")
        augmented[col], augmented[pivot] = augmented[pivot], augmented[col]
        scale = augmented[col][col]
        augmented[col] = [value / scale for value in augmented[col]]
        for row in range(size):
            if row == col:
                continue
            factor = augmented[row][col]
            if factor == 0:
                continue
            augmented[row] = [
                augmented[row][idx] - factor * augmented[col][idx]
                for idx in range(size + 1)
            ]
    return [augmented[row][-1] for row in range(size)]


def _fit_linear_regression(x: list[list[float]], y: list[float]) -> dict[str, Any]:
    if not x:
        raise ValueError("training data is empty")
    width = len(x[0]) + 1
    xtx = [[0.0 for _ in range(width)] for _ in range(width)]
    xty = [0.0 for _ in range(width)]
    for features, target in zip(x, y, strict=True):
        row = [1.0, *features]
        for i in range(width):
            xty[i] += row[i] * target
            for j in range(width):
                xtx[i][j] += row[i] * row[j]
    # Small ridge term avoids singularity while leaving the intercept effectively unpenalized.
    for index in range(1, width):
        xtx[index][index] += 1e-9
    weights = _solve_linear_system(xtx, xty)
    return {"kind": "linear_regression", "intercept": weights[0], "weights": weights[1:]}


def _predict_linear(model: Mapping[str, Any], features: list[float]) -> float:
    return float(model["intercept"]) + sum(
        float(weight) * value
        for weight, value in zip(model["weights"], features, strict=True)
    )


def _fit_mean(y: list[float]) -> dict[str, Any]:
    return {"kind": "mean_baseline", "mean": sum(y) / len(y)}


def _fit_majority(y: list[str]) -> dict[str, Any]:
    counts: dict[str, int] = {}
    for value in y:
        counts[value] = counts.get(value, 0) + 1
    winner = sorted(counts.items(), key=lambda item: (-item[1], item[0]))[0][0]
    return {"kind": "majority_baseline", "class": winner, "counts": counts}


def _fit_nearest_centroid(x: list[list[float]], y: list[str]) -> dict[str, Any]:
    sums: dict[str, list[float]] = {}
    counts: dict[str, int] = {}
    for features, label in zip(x, y, strict=True):
        if label not in sums:
            sums[label] = [0.0] * len(features)
            counts[label] = 0
        counts[label] += 1
        for index, value in enumerate(features):
            sums[label][index] += value
    centroids = {
        label: [value / counts[label] for value in values]
        for label, values in sums.items()
    }
    return {"kind": "nearest_centroid", "centroids": centroids}


def _predict_classification(model: Mapping[str, Any], features: list[float]) -> str:
    if model["kind"] == "majority_baseline":
        return str(model["class"])
    centroids = dict(model["centroids"])
    ranked = []
    for label, center in centroids.items():
        distance = sum(
            (value - float(expected)) ** 2
            for value, expected in zip(features, center, strict=True)
        )
        ranked.append((distance, str(label)))
    return sorted(ranked)[0][1]


def _regression_metrics(actual: list[float], predicted: list[float]) -> dict[str, float]:
    if not actual:
        raise ValueError("evaluation data is empty")
    errors = [pred - truth for truth, pred in zip(actual, predicted, strict=True)]
    mae = sum(abs(value) for value in errors) / len(errors)
    mse = sum(value * value for value in errors) / len(errors)
    mean_actual = sum(actual) / len(actual)
    denominator = sum((value - mean_actual) ** 2 for value in actual)
    r2 = 1.0 - (sum(value * value for value in errors) / denominator) if denominator else 0.0
    return {"mae": mae, "mse": mse, "rmse": math.sqrt(mse), "r2": r2}


def _classification_metrics(actual: list[str], predicted: list[str]) -> dict[str, float]:
    if not actual:
        raise ValueError("evaluation data is empty")
    correct = sum(a == p for a, p in zip(actual, predicted, strict=True))
    return {"accuracy": correct / len(actual)}


def agentic_ml_plan(
    *,
    task: str,
    source_id: str,
    feature_columns: Iterable[str],
    label_column: str,
    model_name: str,
    version: str,
    train_fraction: float = 0.8,
    seed: int = 42,
    candidates: Iterable[str] | None = None,
    max_rows: int = 100_000,
) -> dict[str, Any]:
    task_key = str(task).casefold()
    if task_key not in {"regression", "classification"}:
        raise ValueError("task must be regression or classification")
    features = [_name(item, "feature column") for item in feature_columns]
    if not features:
        raise ValueError("at least one feature column is required")
    if not 0.5 <= float(train_fraction) <= 0.95:
        raise ValueError("train_fraction must be between 0.5 and 0.95")
    default_candidates = (
        ["mean_baseline", "linear_regression"]
        if task_key == "regression"
        else ["majority_baseline", "nearest_centroid"]
    )
    selected = list(candidates or default_candidates)
    allowed = set(default_candidates)
    if len(selected) < 2 or any(item not in allowed for item in selected):
        raise ValueError(
            f"candidates for {task_key} must contain at least two of: {', '.join(default_candidates)}"
        )
    payload = {
        "task": task_key,
        "source_id": str(source_id),
        "feature_columns": features,
        "label_column": _name(label_column, "label column"),
        "model_name": _name(model_name, "model name"),
        "version": _name(version, "version"),
        "train_fraction": float(train_fraction),
        "seed": int(seed),
        "candidates": selected,
        "max_rows": max(10, min(int(max_rows), 1_000_000)),
        "registry_relative_path": f".ade/ml/registry/{_name(model_name, 'model name')}/{_name(version, 'version')}.json",
    }
    return {
        "status": "PASS",
        "mode": "PLAN_ONLY",
        **payload,
        "objective": {
            "metric": "mae" if task_key == "regression" else "accuracy",
            "direction": "minimize" if task_key == "regression" else "maximize",
        },
        "approval_fingerprint": _digest(payload),
    }


class AgenticMLWorkflow:
    def __init__(self, workspace: str | Path) -> None:
        self.workspace = Path(workspace).expanduser().resolve()
        self.workspace.mkdir(parents=True, exist_ok=True)

    def _registry_path(self, plan: Mapping[str, Any]) -> Path:
        relative = Path(str(plan["registry_relative_path"]))
        target = (self.workspace / relative).resolve()
        if target != self.workspace and self.workspace not in target.parents:
            raise ValueError("model registry path escapes workspace")
        return target

    @staticmethod
    def _plan_payload(plan: Mapping[str, Any]) -> dict[str, Any]:
        return {
            key: plan[key]
            for key in (
                "task", "source_id", "feature_columns", "label_column",
                "model_name", "version", "train_fraction", "seed",
                "candidates", "max_rows", "registry_relative_path",
            )
        }

    def run(
        self,
        plan: Mapping[str, Any],
        records: Iterable[Mapping[str, Any]],
        *,
        approval_fingerprint: str,
    ) -> dict[str, Any]:
        payload = self._plan_payload(plan)
        expected = _digest(payload)
        if approval_fingerprint != expected or plan.get("approval_fingerprint") != expected:
            return {"status": "STALE_APPROVAL", "approval_fingerprint": expected}

        materialized = [dict(row) for row in records]
        if len(materialized) < 10:
            raise ValueError("at least 10 records are required for train/evaluation")
        if len(materialized) > int(plan["max_rows"]):
            materialized = materialized[: int(plan["max_rows"])]

        feature_columns = list(plan["feature_columns"])
        label_column = str(plan["label_column"])
        prepared_x: list[list[float]] = []
        prepared_y: list[Any] = []
        rejected = []
        for index, row in enumerate(materialized):
            try:
                features = [
                    _float(row.get(column), column)
                    for column in feature_columns
                ]
                label = row.get(label_column)
                if label is None:
                    raise ValueError("label is missing")
                if plan["task"] == "regression":
                    label = _float(label, label_column)
                else:
                    label = str(label)
                prepared_x.append(features)
                prepared_y.append(label)
            except ValueError as exc:
                rejected.append({"row": index, "reason": str(exc)})

        if len(prepared_x) < 10:
            raise ValueError("fewer than 10 valid records remain after data preparation")

        indices = list(range(len(prepared_x)))
        random.Random(int(plan["seed"])).shuffle(indices)
        cut = max(1, min(len(indices) - 1, int(len(indices) * float(plan["train_fraction"]))))
        train_idx = indices[:cut]
        test_idx = indices[cut:]
        train_x = [prepared_x[i] for i in train_idx]
        test_x = [prepared_x[i] for i in test_idx]
        train_y = [prepared_y[i] for i in train_idx]
        test_y = [prepared_y[i] for i in test_idx]

        candidate_results = []
        for candidate in plan["candidates"]:
            if plan["task"] == "regression":
                model = (
                    _fit_mean(train_y)
                    if candidate == "mean_baseline"
                    else _fit_linear_regression(train_x, train_y)
                )
                predicted = [
                    float(model["mean"])
                    if candidate == "mean_baseline"
                    else _predict_linear(model, features)
                    for features in test_x
                ]
                metrics = _regression_metrics(test_y, predicted)
            else:
                model = (
                    _fit_majority(train_y)
                    if candidate == "majority_baseline"
                    else _fit_nearest_centroid(train_x, train_y)
                )
                predicted = [
                    _predict_classification(model, features)
                    for features in test_x
                ]
                metrics = _classification_metrics(test_y, predicted)
            candidate_results.append(
                {
                    "candidate": candidate,
                    "model": model,
                    "metrics": metrics,
                    "model_fingerprint": _digest(model),
                }
            )

        metric = str(plan["objective"]["metric"])
        reverse = plan["objective"]["direction"] == "maximize"
        ranked = sorted(
            candidate_results,
            key=lambda item: float(item["metrics"][metric]),
            reverse=reverse,
        )
        winner = ranked[0]
        data_evidence = {
            "source_id": plan["source_id"],
            "rows_received": len(materialized),
            "rows_valid": len(prepared_x),
            "rows_rejected": len(rejected),
            "train_rows": len(train_idx),
            "test_rows": len(test_idx),
            "feature_columns": feature_columns,
            "label_column": label_column,
            "data_fingerprint": _digest(
                [
                    {
                        "x": prepared_x[index],
                        "y": prepared_y[index],
                    }
                    for index in range(len(prepared_x))
                ]
            ),
        }
        artifact = {
            "artifact_format": "ade-portable-model/v1",
            "task": plan["task"],
            "model_name": plan["model_name"],
            "version": plan["version"],
            "feature_columns": feature_columns,
            "label_column": label_column,
            "selected_candidate": winner["candidate"],
            "model": winner["model"],
            "metrics": winner["metrics"],
            "candidate_metrics": {
                item["candidate"]: item["metrics"]
                for item in candidate_results
            },
            "lineage": {
                "source": plan["source_id"],
                "features": feature_columns,
                "label": label_column,
                "target": f"{plan['model_name']}:{plan['version']}",
            },
            "data_evidence": data_evidence,
            "operation_estimate": {
                "row_feature_operations": len(prepared_x) * len(feature_columns),
                "estimated_local_cost_usd": 0.0,
            },
        }
        artifact["artifact_fingerprint"] = _digest(artifact)
        path = self._registry_path(plan)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(
            json.dumps(artifact, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )

        verification_sample = prepared_x[test_idx[0]]
        if plan["task"] == "regression":
            prediction: Any = (
                float(winner["model"]["mean"])
                if winner["candidate"] == "mean_baseline"
                else _predict_linear(winner["model"], verification_sample)
            )
            inference_valid = math.isfinite(float(prediction))
        else:
            prediction = _predict_classification(winner["model"], verification_sample)
            inference_valid = str(prediction) in {
                str(value) for value in prepared_y
            }
        verification = {
            "status": "PASS" if inference_valid else "FAIL",
            "sample_features": verification_sample,
            "prediction": prediction,
            "artifact_fingerprint": artifact["artifact_fingerprint"],
        }
        return {
            "status": "PASS" if inference_valid else "FAIL_VERIFY",
            "model_name": plan["model_name"],
            "version": plan["version"],
            "registry_path": str(path.relative_to(self.workspace)),
            "objective": dict(plan["objective"]),
            "candidate_results": [
                {
                    key: value
                    for key, value in item.items()
                    if key != "model"
                }
                for item in candidate_results
            ],
            "selected_candidate": winner["candidate"],
            "selected_metrics": winner["metrics"],
            "artifact_fingerprint": artifact["artifact_fingerprint"],
            "data_evidence": data_evidence,
            "rejected_rows": rejected[:100],
            "lineage": artifact["lineage"],
            "operation_estimate": artifact["operation_estimate"],
            "verification": verification,
            "evidence_fingerprint": _digest(
                {
                    "artifact": artifact["artifact_fingerprint"],
                    "data": data_evidence,
                    "verification": verification,
                }
            ),
            "approval_fingerprint": expected,
        }

    def artifact(self, model_name: str, version: str) -> dict[str, Any]:
        path = (
            self.workspace
            / ".ade"
            / "ml"
            / "registry"
            / _name(model_name, "model name")
            / f"{_name(version, 'version')}.json"
        ).resolve()
        registry_root = (self.workspace / ".ade" / "ml" / "registry").resolve()
        if registry_root not in path.parents:
            raise ValueError("artifact path escapes local registry")
        if not path.exists():
            raise KeyError(f"model artifact not found: {model_name}:{version}")
        value = json.loads(path.read_text(encoding="utf-8"))
        if value.get("artifact_fingerprint") != _digest(
            {key: item for key, item in value.items() if key != "artifact_fingerprint"}
        ):
            raise ValueError("model artifact fingerprint mismatch")
        return value

    def predict(
        self,
        model_name: str,
        version: str,
        record: Mapping[str, Any],
    ) -> dict[str, Any]:
        artifact = self.artifact(model_name, version)
        features = [
            _float(record.get(column), column)
            for column in artifact["feature_columns"]
        ]
        model = artifact["model"]
        if artifact["task"] == "regression":
            prediction: Any = (
                float(model["mean"])
                if model["kind"] == "mean_baseline"
                else _predict_linear(model, features)
            )
        else:
            prediction = _predict_classification(model, features)
        evidence = {
            "model_name": model_name,
            "version": version,
            "artifact_fingerprint": artifact["artifact_fingerprint"],
            "features": features,
            "prediction": prediction,
        }
        return {
            "status": "PASS",
            **evidence,
            "inference_fingerprint": _digest(evidence),
        }

    def list_artifacts(self) -> list[dict[str, Any]]:
        root = self.workspace / ".ade" / "ml" / "registry"
        if not root.exists():
            return []
        values = []
        for path in sorted(root.glob("*/*.json")):
            artifact = json.loads(path.read_text(encoding="utf-8"))
            values.append(
                {
                    "model_name": artifact.get("model_name"),
                    "version": artifact.get("version"),
                    "selected_candidate": artifact.get("selected_candidate"),
                    "metrics": artifact.get("metrics"),
                    "artifact_fingerprint": artifact.get("artifact_fingerprint"),
                    "path": path.relative_to(self.workspace).as_posix(),
                }
            )
        return values
