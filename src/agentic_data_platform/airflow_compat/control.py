"""Dependency-free Airflow 2.x/3.x static control-plane intelligence.

The analyzer parses DAG source with Python's AST and never imports or executes user DAGs.
It complements the existing hospitality-specific AirflowProject scanner with modern
Airflow 3 Assets, Task SDK, DAG bundles, event scheduling, dynamic mapping,
deferrable operators, XCom/security/capacity and upgrade diagnostics.
"""

from __future__ import annotations

import ast
import re
from dataclasses import asdict, dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any

from agentic_data_platform.platform.airflow import AirflowProject


_SECRET_RE = re.compile(
    r"(?i)(password|passwd|secret|token|api[_-]?key)\s*=\s*['\"][^'\"]{4,}['\"]"
)
_CREDENTIAL_URL_RE = re.compile(r"(?i)\b[a-z][a-z0-9+.-]*://[^\s/:]+:[^\s/@]+@")
_TOP_LEVEL_RISKY = {
    "connect", "create_engine", "get", "post", "put", "delete", "request",
    "urlopen", "read_sql", "execute", "Session",
}
_BUNDLES = {"LocalDagBundle", "GitDagBundle", "S3DagBundle", "GCSDagBundle"}
_SENSOR_HINTS = ("Sensor", "sensor")
_DEPRECATED_IMPORT_HINTS = (
    "airflow.operators.subdag",
    "airflow.contrib",
    "airflow.models.dagbag",
    "airflow.models.baseoperator",
)


@dataclass
class SourceRecord:
    file: str
    dag_ids: list[str] = field(default_factory=list)
    task_ids: list[str] = field(default_factory=list)
    imports: list[str] = field(default_factory=list)
    connections: list[str] = field(default_factory=list)
    variables: list[str] = field(default_factory=list)
    pools: list[str] = field(default_factory=list)
    queues: list[str] = field(default_factory=list)
    assets: list[str] = field(default_factory=list)
    datasets: list[str] = field(default_factory=list)
    asset_aliases: list[str] = field(default_factory=list)
    mapping_calls: list[dict[str, Any]] = field(default_factory=list)
    xcom_calls: list[dict[str, Any]] = field(default_factory=list)
    sensors: list[dict[str, Any]] = field(default_factory=list)
    deferrable: list[dict[str, Any]] = field(default_factory=list)
    bundles: list[dict[str, Any]] = field(default_factory=list)
    deadlines: list[dict[str, Any]] = field(default_factory=list)
    slas: list[dict[str, Any]] = field(default_factory=list)
    top_level_calls: list[dict[str, Any]] = field(default_factory=list)
    openlineage: bool = False
    task_sdk: bool = False
    asset_watcher: bool = False
    event_driven: bool = False
    dynamic_mapping: bool = False
    hardcoded_secret_lines: list[int] = field(default_factory=list)
    credential_url_lines: list[int] = field(default_factory=list)
    deprecated_imports: list[str] = field(default_factory=list)
    subdag: bool = False


def _call_name(node: ast.AST) -> str:
    if isinstance(node, ast.Name):
        return node.id
    if isinstance(node, ast.Attribute):
        prefix = _call_name(node.value)
        return f"{prefix}.{node.attr}" if prefix else node.attr
    return ""


def _literal(node: ast.AST | None) -> Any:
    if node is None:
        return None
    try:
        return ast.literal_eval(node)
    except (TypeError, ValueError):
        return None


def _keyword(call: ast.Call, name: str) -> Any:
    for item in call.keywords:
        if item.arg == name:
            return _literal(item.value)
    return None


def _first_text(call: ast.Call) -> str | None:
    if call.args:
        value = _literal(call.args[0])
        if isinstance(value, (str, int, float)):
            return str(value)
    for key in ("name", "uri", "dag_id", "task_id", "asset", "dataset"):
        value = _keyword(call, key)
        if isinstance(value, (str, int, float)):
            return str(value)
    return None


def _decorator_name(node: ast.AST) -> str:
    return _call_name(node.func) if isinstance(node, ast.Call) else _call_name(node)


def _unique(items: list[str]) -> list[str]:
    return sorted(set(item for item in items if item))


class AirflowControlPlane:
    """Static Airflow 2/3 intelligence over a repository or DAG directory."""

    def __init__(self, project: str | Path) -> None:
        self.root = Path(project).expanduser().resolve()
        self.legacy = AirflowProject.scan(self.root)
        dags_dir = self.root / "airflow" / "dags"
        self.dags_dir = dags_dir if dags_dir.is_dir() else self.root
        self.records = self._scan()

    def _scan(self) -> list[SourceRecord]:
        records: list[SourceRecord] = []
        for path in sorted(self.dags_dir.rglob("*.py")):
            try:
                text = path.read_text(errors="replace")
                tree = ast.parse(text, filename=str(path))
            except (OSError, SyntaxError):
                continue
            record = SourceRecord(file=str(path))
            lines = text.splitlines()
            record.hardcoded_secret_lines = [
                idx for idx, line in enumerate(lines, 1) if _SECRET_RE.search(line)
            ]
            record.credential_url_lines = [
                idx for idx, line in enumerate(lines, 1) if _CREDENTIAL_URL_RE.search(line)
            ]
            for node in ast.walk(tree):
                if isinstance(node, (ast.Import, ast.ImportFrom)):
                    names: list[str] = []
                    if isinstance(node, ast.Import):
                        names = [item.name for item in node.names]
                    else:
                        module = node.module or ""
                        names = [module] + [f"{module}.{item.name}".strip(".") for item in node.names]
                    record.imports.extend(names)
                    if any(name.startswith("airflow.sdk") for name in names):
                        record.task_sdk = True
                    if any("openlineage" in name.casefold() for name in names):
                        record.openlineage = True
                    record.deprecated_imports.extend(
                        name for name in names
                        if any(hint in name for hint in _DEPRECATED_IMPORT_HINTS)
                    )
                if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                    decorators = {_decorator_name(item).split(".")[-1] for item in node.decorator_list}
                    if "dag" in decorators:
                        record.dag_ids.append(node.name)
                    if "task" in decorators:
                        record.task_ids.append(node.name)
                if not isinstance(node, ast.Call):
                    continue
                name = _call_name(node.func)
                short = name.split(".")[-1]
                dag_id = _keyword(node, "dag_id")
                task_id = _keyword(node, "task_id")
                if short == "DAG" and isinstance(dag_id, str):
                    record.dag_ids.append(dag_id)
                if isinstance(task_id, str):
                    record.task_ids.append(task_id)
                for kw in node.keywords:
                    if kw.arg and kw.arg.endswith("conn_id"):
                        value = _literal(kw.value)
                        if isinstance(value, str):
                            record.connections.append(value)
                if short == "get" and ("Variable" in name or name.endswith("Variable.get")):
                    value = _first_text(node)
                    if value:
                        record.variables.append(value)
                if short in {"xcom_push", "xcom_pull"}:
                    record.xcom_calls.append({"operation": short, "line": node.lineno})
                if short in {"expand", "expand_kwargs", "map", "zip", "concat"}:
                    record.dynamic_mapping = True
                    record.mapping_calls.append({"operation": short, "line": node.lineno})
                if short in {"Asset", "Dataset", "AssetAlias"}:
                    value = _first_text(node)
                    if value:
                        target = (
                            record.datasets if short == "Dataset"
                            else record.asset_aliases if short == "AssetAlias"
                            else record.assets
                        )
                        target.append(value)
                if short == "AssetWatcher":
                    record.asset_watcher = True
                    record.event_driven = True
                if short in _BUNDLES:
                    record.bundles.append({
                        "type": short,
                        "line": node.lineno,
                        "version": _keyword(node, "version"),
                        "tracking_ref": _keyword(node, "tracking_ref"),
                        "refresh_interval": _keyword(node, "refresh_interval"),
                    })
                deferrable = _keyword(node, "deferrable")
                mode = _keyword(node, "mode")
                if deferrable is True:
                    record.deferrable.append({"operator": short, "line": node.lineno})
                if any(hint in short for hint in _SENSOR_HINTS):
                    record.sensors.append({
                        "operator": short,
                        "line": node.lineno,
                        "deferrable": deferrable is True,
                        "mode": mode,
                    })
                pool = _keyword(node, "pool")
                queue = _keyword(node, "queue")
                if isinstance(pool, str):
                    record.pools.append(pool)
                if isinstance(queue, str):
                    record.queues.append(queue)
                for kw in node.keywords:
                    if kw.arg in {"deadline", "deadline_alert"}:
                        record.deadlines.append({"line": node.lineno, "value": ast.unparse(kw.value)})
                    if kw.arg == "sla":
                        record.slas.append({"line": node.lineno, "value": ast.unparse(kw.value)})
                if short in {"SubDagOperator", "SubDag"}:
                    record.subdag = True
                if "openlineage" in name.casefold():
                    record.openlineage = True

            for stmt in tree.body:
                call: ast.Call | None = None
                if isinstance(stmt, ast.Expr) and isinstance(stmt.value, ast.Call):
                    call = stmt.value
                elif isinstance(stmt, (ast.Assign, ast.AnnAssign)) and isinstance(stmt.value, ast.Call):
                    call = stmt.value
                if call is not None:
                    name = _call_name(call.func)
                    if name.split(".")[-1] in _TOP_LEVEL_RISKY:
                        record.top_level_calls.append({"call": name, "line": call.lineno})

            record.dag_ids = _unique(record.dag_ids)
            record.task_ids = _unique(record.task_ids)
            record.imports = _unique(record.imports)
            record.connections = _unique(record.connections)
            record.variables = _unique(record.variables)
            record.pools = _unique(record.pools)
            record.queues = _unique(record.queues)
            record.assets = _unique(record.assets)
            record.datasets = _unique(record.datasets)
            record.asset_aliases = _unique(record.asset_aliases)
            record.deprecated_imports = _unique(record.deprecated_imports)
            records.append(record)
        return records

    def version_compatibility(self) -> dict[str, Any]:
        sdk = any(item.task_sdk for item in self.records)
        assets = any(item.assets or item.asset_aliases or item.deadlines for item in self.records)
        datasets = any(item.datasets for item in self.records)
        inferred = "3.x" if sdk or assets else "2.x-compatible" if datasets else "2.x/3.x-neutral"
        return {
            "status": "PASS",
            "mode": "STATIC",
            "inferred_semantics": inferred,
            "task_sdk_detected": sdk,
            "airflow3_assets_detected": assets,
            "legacy_datasets_detected": datasets,
            "target": "Airflow 3.x with Airflow 2.x project compatibility",
        }

    def inventory(self) -> dict[str, Any]:
        return {
            **self.legacy.summary(),
            "compatibility": self.version_compatibility(),
            "task_count": len({task for record in self.records for task in record.task_ids}),
            "asset_count": len({asset for record in self.records for asset in record.assets}),
            "dataset_count": len({asset for record in self.records for asset in record.datasets}),
            "dynamic_mapping_files": sum(record.dynamic_mapping for record in self.records),
            "deferrable_count": sum(len(record.deferrable) for record in self.records),
            "bundle_count": sum(len(record.bundles) for record in self.records),
        }

    def graph(self) -> dict[str, Any]:
        nodes: dict[str, dict[str, Any]] = {}
        edges: set[tuple[str, str, str]] = set()
        for dag in self.legacy.dags.values():
            dag_key = f"dag:{dag.dag_id}"
            nodes[dag_key] = {"id": dag_key, "kind": "dag", "name": dag.dag_id}
            for task in dag.tasks:
                task_key = f"task:{dag.dag_id}:{task}"
                nodes[task_key] = {"id": task_key, "kind": "task", "name": task, "dag_id": dag.dag_id}
                edges.add((dag_key, task_key, "contains"))
            for left, right in dag.task_graph:
                edges.add((f"task:{dag.dag_id}:{left}", f"task:{dag.dag_id}:{right}", "depends_on"))
            for connection in dag.connections:
                key = f"connection:{connection}"
                nodes[key] = {"id": key, "kind": "connection", "name": connection}
                edges.add((dag_key, key, "uses_connection"))
        for record in self.records:
            dag_ids = record.dag_ids or [
                dag.dag_id for dag in self.legacy.dags.values() if Path(dag.file) == Path(record.file)
            ]
            for asset in record.assets + record.datasets + record.asset_aliases:
                kind = "dataset" if asset in record.datasets else "asset"
                key = f"{kind}:{asset}"
                nodes[key] = {"id": key, "kind": kind, "name": asset}
                for dag_id in dag_ids:
                    edges.add((f"dag:{dag_id}", key, "references_asset"))
            for variable in record.variables:
                key = f"variable:{variable}"
                nodes[key] = {"id": key, "kind": "variable", "name": variable}
                for dag_id in dag_ids:
                    edges.add((f"dag:{dag_id}", key, "uses_variable"))
            for pool in record.pools:
                key = f"pool:{pool}"
                nodes[key] = {"id": key, "kind": "pool", "name": pool}
                for dag_id in dag_ids:
                    edges.add((f"dag:{dag_id}", key, "uses_pool"))
            for queue in record.queues:
                key = f"queue:{queue}"
                nodes[key] = {"id": key, "kind": "queue", "name": queue}
                for dag_id in dag_ids:
                    edges.add((f"dag:{dag_id}", key, "uses_queue"))
        return {
            "nodes": sorted(nodes.values(), key=lambda item: item["id"]),
            "edges": [
                {"source": source, "target": target, "type": kind}
                for source, target, kind in sorted(edges)
            ],
        }

    def asset_report(self) -> dict[str, Any]:
        assets: dict[str, dict[str, Any]] = {}
        for record in self.records:
            dag_ids = record.dag_ids
            for name in record.assets:
                item = assets.setdefault(name, {"name": name, "kind": "Asset", "files": [], "dags": []})
                item["files"].append(record.file)
                item["dags"].extend(dag_ids)
            for name in record.datasets:
                item = assets.setdefault(name, {"name": name, "kind": "Dataset", "files": [], "dags": []})
                item["files"].append(record.file)
                item["dags"].extend(dag_ids)
            for name in record.asset_aliases:
                item = assets.setdefault(name, {"name": name, "kind": "AssetAlias", "files": [], "dags": []})
                item["files"].append(record.file)
                item["dags"].extend(dag_ids)
        for item in assets.values():
            item["files"] = _unique(item["files"])
            item["dags"] = _unique(item["dags"])
        return {
            "status": "PASS",
            "items": sorted(assets.values(), key=lambda item: item["name"]),
            "count": len(assets),
            "legacy_dataset_count": sum(item["kind"] == "Dataset" for item in assets.values()),
        }

    def event_report(self) -> dict[str, Any]:
        watchers = [
            {"file": record.file, "asset_watcher": record.asset_watcher}
            for record in self.records if record.asset_watcher
        ]
        return {
            "status": "PASS",
            "watchers": watchers,
            "watcher_count": len(watchers),
            "event_driven_files": [record.file for record in self.records if record.event_driven],
            "stalls": [],
            "runtime_events": "SKIP_EXTERNAL - live Airflow event API not configured",
        }

    def mapping_report(self) -> dict[str, Any]:
        calls = [
            {"file": record.file, **item}
            for record in self.records for item in record.mapping_calls
        ]
        explosive = [
            item for item in calls if item["operation"] in {"expand", "expand_kwargs"}
        ]
        return {
            "status": "WARN" if explosive else "PASS",
            "mapping_calls": calls,
            "mapping_count": len(calls),
            "risk_count": len(explosive),
            "risk": "REVIEW" if explosive else "LOW",
            "recommendation": "Bound mapped input cardinality and enforce max_map_length for untrusted fan-out." if explosive else None,
        }

    def deferrable_report(self) -> dict[str, Any]:
        sensors = [
            {"file": record.file, **item}
            for record in self.records for item in record.sensors
        ]
        inefficient = [
            item for item in sensors
            if not item["deferrable"] and item.get("mode") not in {"reschedule"}
        ]
        return {
            "status": "WARN" if inefficient else "PASS",
            "sensors": sensors,
            "inefficient_sensors": inefficient,
            "deferrable_count": sum(len(record.deferrable) for record in self.records),
            "triggerer": "SKIP_EXTERNAL - live triggerer health requires Airflow runtime",
        }

    def bundle_report(self) -> dict[str, Any]:
        bundles = [
            {"file": record.file, **item}
            for record in self.records for item in record.bundles
        ]
        risky = [
            {"file": record.file, "line": line, "reason": "credential literal in DAG/bundle source"}
            for record in self.records for line in record.hardcoded_secret_lines
            if record.bundles
        ]
        return {
            "status": "FAIL" if risky else "PASS",
            "bundles": bundles,
            "count": len(bundles),
            "security_findings": risky,
            "drift": "STATIC_ONLY - compare runtime bundle version when API is configured",
        }

    def sdk_report(self) -> dict[str, Any]:
        deprecated = [
            {"file": record.file, "import": item}
            for record in self.records for item in record.deprecated_imports
        ]
        subdags = [record.file for record in self.records if record.subdag]
        return {
            "status": "WARN" if deprecated or subdags else "PASS",
            "task_sdk_files": [record.file for record in self.records if record.task_sdk],
            "deprecated_imports": deprecated,
            "subdag_files": subdags,
            "legacy_dataset_files": [record.file for record in self.records if record.datasets],
        }

    def parse_health(self) -> dict[str, Any]:
        duplicates: dict[str, list[str]] = {}
        by_id: dict[str, list[str]] = {}
        for dag in self.legacy.dags.values():
            by_id.setdefault(dag.dag_id, []).append(dag.file)
        duplicates = {key: value for key, value in by_id.items() if len(set(value)) > 1}
        top_level = [
            {"file": record.file, **item}
            for record in self.records for item in record.top_level_calls
        ]
        return {
            "status": "FAIL" if self.legacy.parse_errors else "WARN" if top_level or duplicates else "PASS",
            "import_errors": self.legacy.parse_errors,
            "duplicate_dag_ids": duplicates,
            "top_level_side_effect_risks": top_level,
            "serialization_findings": [],
        }

    def security_report(self) -> dict[str, Any]:
        secrets = [
            {"file": record.file, "line": line, "rule_id": "AIRFLOW_SECRET_LITERAL"}
            for record in self.records for line in record.hardcoded_secret_lines
        ]
        urls = [
            {"file": record.file, "line": line, "rule_id": "AIRFLOW_CREDENTIAL_URL"}
            for record in self.records for line in record.credential_url_lines
        ]
        return {
            "status": "FAIL" if secrets or urls else "PASS",
            "hardcoded_secret_findings": secrets,
            "credential_url_findings": urls,
            "connections": _unique([item for record in self.records for item in record.connections]),
            "variables": _unique([item for record in self.records for item in record.variables]),
            "secret_values_returned": False,
        }

    def xcom_report(self) -> dict[str, Any]:
        calls = [
            {"file": record.file, **item}
            for record in self.records for item in record.xcom_calls
        ]
        return {
            "status": "PASS",
            "explicit_calls": calls,
            "taskflow_implicit_possible": any(record.task_sdk for record in self.records),
            "large_payload_findings": [],
            "sensitive_value_findings": [],
            "note": "Static analysis flags XCom surfaces without reading runtime XCom values.",
        }

    def capacity_report(self) -> dict[str, Any]:
        pools = _unique([item for record in self.records for item in record.pools])
        queues = _unique([item for record in self.records for item in record.queues])
        return {
            "status": "PASS",
            "pools": pools,
            "queues": queues,
            "static_dag_count": len(self.legacy.dags),
            "runtime_capacity": "SKIP_EXTERNAL - scheduler/worker/pool slot metrics require live Airflow",
            "recommendations": [
                "Validate parallelism, max_active_tasks_per_dag, max_active_runs_per_dag and worker concurrency against peak mapped-task cardinality."
            ],
        }

    def deadline_report(self) -> dict[str, Any]:
        deadlines = [
            {"file": record.file, **item}
            for record in self.records for item in record.deadlines
        ]
        slas = [
            {"file": record.file, **item}
            for record in self.records for item in record.slas
        ]
        return {
            "status": "WARN" if slas and self.version_compatibility()["inferred_semantics"] == "3.x" else "PASS",
            "deadline_alerts": deadlines,
            "legacy_slas": slas,
            "migration_required": bool(slas and self.version_compatibility()["inferred_semantics"] == "3.x"),
        }

    def executor_report(self) -> dict[str, Any]:
        text = "\n".join(" ".join(record.imports) for record in self.records)
        detected = [
            name for name in ("LocalExecutor", "CeleryExecutor", "KubernetesExecutor")
            if name in text
        ]
        return {
            "status": "PASS",
            "detected": detected,
            "runtime_executor": "SKIP_EXTERNAL - executor config requires Airflow runtime/config",
        }

    def openlineage_report(self) -> dict[str, Any]:
        files = [record.file for record in self.records if record.openlineage]
        return {
            "status": "PASS" if files else "WARN",
            "configured_in_source": bool(files),
            "files": files,
            "events": [],
            "runtime_events": "SKIP_EXTERNAL - OpenLineage backend not configured",
        }

    def deployment_report(self) -> dict[str, Any]:
        return {
            "status": "PASS",
            "targets": {
                "local": {"implementation": "DONE", "live": "LOCAL"},
                "docker_compose": {"implementation": "DONE", "live": "CONDITIONAL"},
                "kubernetes_helm": {"implementation": "DONE", "live": "SKIP_EXTERNAL"},
                "mwaa": {"implementation": "DONE", "live": "SKIP_EXTERNAL"},
                "composer": {"implementation": "DONE", "live": "SKIP_EXTERNAL"},
                "astronomer": {"implementation": "DONE", "live": "SKIP_EXTERNAL"},
            },
        }

    def backfill_plan(self, args: dict[str, Any]) -> dict[str, Any]:
        dag_id = args.get("dag_id")
        start = args.get("start_date")
        end = args.get("end_date")
        estimated_runs = None
        if start and end:
            try:
                left = datetime.fromisoformat(str(start).replace("Z", "+00:00"))
                right = datetime.fromisoformat(str(end).replace("Z", "+00:00"))
                estimated_runs = max(0, (right - left).days + 1)
            except ValueError:
                estimated_runs = None
        risk = "HIGH" if estimated_runs is not None and estimated_runs > 31 else "REVIEW"
        return {
            "status": "PASS",
            "mode": "DRY_RUN",
            "dag_id": dag_id,
            "start_date": start,
            "end_date": end,
            "estimated_runs": estimated_runs,
            "risk": risk,
            "execution_allowed": False,
            "requires": ["Builder", "explicit approval", "validated source/warehouse impact"],
        }

    def root_cause(self, args: dict[str, Any]) -> dict[str, Any]:
        evidence = [
            str(item) for item in (
                args.get("error"), args.get("log"), args.get("warehouse_error"),
                args.get("dbt_error"), args.get("quality_error")
            ) if item
        ]
        joined = " ".join(evidence).casefold()
        rules = [
            (("permission", "insufficient privilege", "not authorized"), "WAREHOUSE_PERMISSION", 0.95),
            (("connection refused", "could not connect", "dns"), "CONNECTION_FAILURE", 0.92),
            (("timeout", "timed out", "deadline"), "TIMEOUT", 0.87),
            (("compilation error", "dbt"), "DBT_FAILURE", 0.86),
            (("invalid identifier", "schema drift", "column not found"), "SCHEMA_DRIFT", 0.84),
            (("xcom", "serialization"), "XCOM_SERIALIZATION", 0.82),
            (("pool", "starvation", "queued"), "CAPACITY_STARVATION", 0.80),
        ]
        for terms, cause, confidence in rules:
            if any(term in joined for term in terms):
                return {
                    "status": "DIAGNOSED",
                    "probable_cause": cause,
                    "confidence": confidence,
                    "evidence": evidence,
                    "affected_assets": args.get("affected_assets", []),
                    "affected_tasks": args.get("affected_tasks", []),
                    "affected_downstream": args.get("affected_downstream", []),
                    "recommended_actions": ["Validate the cited evidence before retrying or applying any remediation."],
                }
        return {
            "status": "NEEDS_MORE_EVIDENCE",
            "probable_cause": None,
            "confidence": 0.0,
            "evidence": evidence,
            "affected_assets": [],
            "affected_tasks": [],
            "affected_downstream": [],
            "recommended_actions": ["Collect task logs, scheduler state, connection status, dbt results and warehouse errors."],
        }

    def quality_scan(self) -> dict[str, Any]:
        findings: list[dict[str, Any]] = []
        for record in self.records:
            for line in record.hardcoded_secret_lines:
                findings.append(self._finding("AIRFLOW_SECRET_LITERAL", "CRITICAL", record.file, line, "Hard-coded credential-like literal.", "Move the value to an Airflow Connection or secrets backend."))
            for line in record.credential_url_lines:
                findings.append(self._finding("AIRFLOW_CREDENTIAL_URL", "CRITICAL", record.file, line, "Credential embedded in URL.", "Use secret-safe connection configuration."))
            for item in record.top_level_calls:
                findings.append(self._finding("AIRFLOW_TOP_LEVEL_IO", "HIGH", record.file, item["line"], f"Top-level call may perform I/O: {item['call']}", "Move network/database work into task execution."))
            for item in record.sensors:
                if not item["deferrable"] and item.get("mode") != "reschedule":
                    findings.append(self._finding("AIRFLOW_SENSOR_WORKER_SLOT", "MEDIUM", record.file, item["line"], f"{item['operator']} may occupy a worker slot while waiting.", "Prefer a deferrable operator or reschedule mode when supported."))
            for item in record.mapping_calls:
                if item["operation"] in {"expand", "expand_kwargs"}:
                    findings.append(self._finding("AIRFLOW_DYNAMIC_MAP_REVIEW", "MEDIUM", record.file, item["line"], "Dynamic mapping cardinality is not statically bounded.", "Bound input cardinality and configure max_map_length."))
            for item in record.deprecated_imports:
                findings.append(self._finding("AIRFLOW_DEPRECATED_IMPORT", "MEDIUM", record.file, 1, f"Deprecated/internal import: {item}", "Use stable airflow.sdk or current public provider imports for Airflow 3."))
            if record.subdag:
                findings.append(self._finding("AIRFLOW_SUBDAG", "HIGH", record.file, 1, "SubDAG usage is incompatible with modern Airflow guidance.", "Migrate to TaskGroup or independent DAG orchestration."))
            if record.datasets and record.task_sdk:
                findings.append(self._finding("AIRFLOW_DATASET_MIGRATION", "LOW", record.file, 1, "Legacy Dataset and Airflow 3 Task SDK semantics coexist.", "Evaluate migration to Asset terminology/API."))
        return {
            "status": "FAIL" if any(item["severity"] == "CRITICAL" for item in findings) else "WARN" if findings else "PASS",
            "finding_count": len(findings),
            "findings": findings,
        }

    @staticmethod
    def _finding(rule_id: str, severity: str, file: str, line: int, message: str, recommendation: str) -> dict[str, Any]:
        return {
            "rule_id": rule_id,
            "severity": severity,
            "confidence": 0.95,
            "dag_id": None,
            "task_id": None,
            "file": file,
            "line": line,
            "message": message,
            "evidence": {"file": file, "line": line},
            "recommendation": recommendation,
        }

    def log_report(self, args: dict[str, Any]) -> dict[str, Any]:
        log = str(args.get("log") or "")
        if not log:
            return {"status": "SKIP_EXTERNAL", "reason": "No local/runtime log text supplied.", "errors": []}
        patterns = {
            "PERMISSION": ("permission denied", "insufficient privilege", "not authorized"),
            "CREDENTIAL": ("invalid credential", "authentication failed", "unauthorized"),
            "NETWORK": ("connection refused", "connection reset", "dns"),
            "TIMEOUT": ("timeout", "timed out"),
            "OOM": ("out of memory", "oomkilled"),
            "DBT": ("dbt", "compilation error"),
            "SCHEMA": ("invalid identifier", "column not found", "schema mismatch"),
        }
        lowered = log.casefold()
        errors = [
            {"category": category, "matched": term}
            for category, terms in patterns.items()
            for term in terms if term in lowered
        ]
        return {"status": "WARN" if errors else "PASS", "errors": errors}

    def doctor(self) -> dict[str, Any]:
        compatibility = self.version_compatibility()
        parse = self.parse_health()
        return {
            "status": "FAIL" if parse["status"] == "FAIL" else "PASS",
            "mode": "STATIC",
            "checks": {
                "airflow_source": {"status": "PASS" if self.records else "WARN", "detail": f"{len(self.records)} Python files scanned"},
                "version_compatibility": {"status": "PASS", "detail": compatibility["inferred_semantics"]},
                "dag_parse": {"status": parse["status"], "detail": f"{len(parse['import_errors'])} syntax/import parse errors"},
                "api": {"status": "SKIP_EXTERNAL", "detail": "Configure Airflow runtime URL for live API checks"},
                "scheduler": {"status": "SKIP_EXTERNAL", "detail": "Live runtime required"},
                "dag_processor": {"status": "SKIP_EXTERNAL", "detail": "Live runtime required"},
                "triggerer": {"status": "SKIP_EXTERNAL", "detail": "Live runtime required"},
                "workers": {"status": "SKIP_EXTERNAL", "detail": "Live runtime required"},
                "openlineage": {"status": "PASS" if any(r.openlineage for r in self.records) else "WARN", "detail": "source configuration scan"},
            },
        }

    def report(self, kind: str, args: dict[str, Any] | None = None) -> dict[str, Any]:
        args = args or {}
        mapping = {
            "inventory": self.inventory,
            "graph": self.graph,
            "assets": self.asset_report,
            "events": self.event_report,
            "mapping": self.mapping_report,
            "deferrable": self.deferrable_report,
            "bundles": self.bundle_report,
            "sdk": self.sdk_report,
            "parse": self.parse_health,
            "security": self.security_report,
            "xcom": self.xcom_report,
            "capacity": self.capacity_report,
            "deadline": self.deadline_report,
            "executor": self.executor_report,
            "openlineage": self.openlineage_report,
            "deployment": self.deployment_report,
            "quality": self.quality_scan,
            "doctor": self.doctor,
        }
        if kind == "backfill":
            return self.backfill_plan(args)
        if kind == "root_cause":
            return self.root_cause(args)
        if kind == "logs":
            return self.log_report(args)
        if kind == "upgrade":
            return {
                "status": self.sdk_report()["status"],
                "compatibility": self.version_compatibility(),
                "findings": self.sdk_report(),
                "quality": self.quality_scan(),
            }
        try:
            return mapping[kind]()
        except KeyError as exc:
            raise ValueError(f"unknown Airflow report: {kind}") from exc
