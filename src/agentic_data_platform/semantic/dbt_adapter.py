"""dbt Semantic Layer / MetricFlow adapter for the ADE semantic registry."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml

from agentic_data_platform.semantic.registry import SemanticElement, SemanticRegistry


_IGNORED = {".git", "target", "dbt_packages", "logs", "node_modules", ".venv", "venv"}


def _yaml_files(root: Path) -> list[Path]:
    files: list[Path] = []
    for path in root.rglob("*"):
        if not path.is_file() or path.suffix.casefold() not in {".yml", ".yaml"}:
            continue
        if any(part in _IGNORED for part in path.relative_to(root).parts):
            continue
        files.append(path)
    return sorted(files)


def ingest_dbt_semantic_project(
    registry: SemanticRegistry,
    project_root: str | Path,
    *,
    resource_name: str | None = None,
) -> dict[str, Any]:
    """Ingest dbt semantic_models, metrics and saved_queries into ADE."""
    root = Path(project_root).expanduser().resolve()
    if not root.is_dir():
        raise FileNotFoundError(root)

    semantic_models: list[tuple[Path, dict[str, Any]]] = []
    metrics: list[tuple[Path, dict[str, Any]]] = []
    saved_queries: list[tuple[Path, dict[str, Any]]] = []
    parsed_files: list[str] = []

    for path in _yaml_files(root):
        payload = yaml.safe_load(path.read_text()) or {}
        if not isinstance(payload, dict):
            continue
        found = False
        for item in payload.get("semantic_models") or []:
            if isinstance(item, dict):
                semantic_models.append((path, item))
                found = True
        for item in payload.get("metrics") or []:
            if isinstance(item, dict):
                metrics.append((path, item))
                found = True
        for item in payload.get("saved_queries") or []:
            if isinstance(item, dict):
                saved_queries.append((path, item))
                found = True
        if found:
            parsed_files.append(str(path.relative_to(root)))

    name = resource_name or root.name
    resource_id = registry.upsert_resource(
        name=name,
        provider="dbt-semantic-layer",
        description=f"dbt Semantic Layer / MetricFlow project: {name}",
        metadata={
            "project_root": str(root),
            "files": sorted(set(parsed_files)),
            "semantic_model_count": len(semantic_models),
            "metric_count": len(metrics),
            "saved_query_count": len(saved_queries),
        },
    )

    elements: list[SemanticElement] = []
    relationships: list[dict[str, Any]] = []

    for source, model in semantic_models:
        model_name = str(model.get("name") or "").strip()
        if not model_name:
            continue
        elements.append(
            SemanticElement(
                "semantic_model",
                model_name,
                description=str(model.get("description") or ""),
                expression=str(model.get("model") or ""),
                metadata={
                    "source": str(source.relative_to(root)),
                    "defaults": model.get("defaults") or {},
                    "config": model.get("config") or {},
                },
            )
        )

        for entity in model.get("entities") or []:
            if not isinstance(entity, dict) or not entity.get("name"):
                continue
            entity_name = str(entity["name"])
            entity_type = str(entity.get("type") or "")
            elements.append(
                SemanticElement(
                    "entity",
                    entity_name,
                    parent=model_name,
                    description=str(entity.get("description") or ""),
                    expression=str(entity.get("expr") or entity_name),
                    data_type=entity_type,
                    metadata={
                        key: value
                        for key, value in entity.items()
                        if key not in {"name", "description", "expr", "type"}
                    },
                )
            )
            if entity_type.casefold() == "foreign":
                relationships.append(
                    {
                        "name": f"{model_name}.{entity_name}",
                        "left_table": model_name,
                        "right_table": entity_name,
                        "relationship": "metricflow_foreign_entity",
                        "expression": entity.get("expr") or entity_name,
                    }
                )

        for dimension in model.get("dimensions") or []:
            if not isinstance(dimension, dict) or not dimension.get("name"):
                continue
            dimension_name = str(dimension["name"])
            dimension_type = str(dimension.get("type") or "")
            kind = "time_dimension" if dimension_type.casefold() == "time" else "dimension"
            elements.append(
                SemanticElement(
                    kind,
                    dimension_name,
                    parent=model_name,
                    description=str(dimension.get("description") or ""),
                    expression=str(dimension.get("expr") or dimension_name),
                    data_type=dimension_type,
                    metadata={
                        key: value
                        for key, value in dimension.items()
                        if key not in {"name", "description", "expr", "type"}
                    },
                )
            )

        for measure in model.get("measures") or []:
            if not isinstance(measure, dict) or not measure.get("name"):
                continue
            measure_name = str(measure["name"])
            elements.append(
                SemanticElement(
                    "measure",
                    measure_name,
                    parent=model_name,
                    description=str(measure.get("description") or ""),
                    expression=str(measure.get("expr") or measure_name),
                    data_type=str(measure.get("agg") or ""),
                    metadata={
                        key: value
                        for key, value in measure.items()
                        if key not in {"name", "description", "expr", "agg"}
                    },
                )
            )

    for source, metric in metrics:
        metric_name = str(metric.get("name") or "").strip()
        if not metric_name:
            continue
        type_params = metric.get("type_params") or {}
        expression = ""
        if isinstance(type_params, dict):
            expression = str(type_params.get("measure") or type_params.get("expr") or "")
        elements.append(
            SemanticElement(
                "metric",
                metric_name,
                description=str(metric.get("description") or ""),
                expression=expression,
                data_type=str(metric.get("type") or ""),
                metadata={
                    "source": str(source.relative_to(root)),
                    **{
                        key: value
                        for key, value in metric.items()
                        if key not in {"name", "description", "type"}
                    },
                },
            )
        )

    for source, saved in saved_queries:
        saved_name = str(saved.get("name") or "").strip()
        if not saved_name:
            continue
        elements.append(
            SemanticElement(
                "saved_query",
                saved_name,
                description=str(saved.get("description") or ""),
                metadata={
                    "source": str(source.relative_to(root)),
                    **{key: value for key, value in saved.items() if key not in {"name", "description"}},
                },
            )
        )

    registry.replace_contents(
        resource_id,
        elements=elements,
        relationships=relationships,
        verified_queries=[],
    )
    return registry.show(resource_id)
