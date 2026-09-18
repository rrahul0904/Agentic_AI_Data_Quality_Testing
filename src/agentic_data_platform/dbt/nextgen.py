"""dbt-Summit-inspired, provider-neutral intelligence for ADE.

This module implements open, deterministic equivalents of the useful product
patterns described by dbt's 2026 launch set: state-aware builds, project-aware
assistant context, governed conversational exploration, BI-as-code validation,
local lake compute, enterprise context bundles, and an agent/MCP schema export.
It does not depend on or impersonate proprietary dbt services.
"""

from __future__ import annotations

from collections import deque
import hashlib
import json
from pathlib import Path
import re
import shutil
import subprocess
from typing import Any, Iterable

import yaml

from agentic_data_platform.dbt.intelligence import get_changed_nodes
from agentic_data_platform.dbt.manifest_graph import DbtArtifacts, DbtManifestGraph
from agentic_data_platform.semantic.registry import SemanticRegistry


_TOKEN = re.compile(r"[A-Za-z0-9_.$-]+")
_READ_ONLY_SQL = re.compile(r"^\s*(select|with|describe|show|explain|pragma)\b", re.I)


def _load_json(path: str | Path) -> dict[str, Any]:
    target = Path(path).expanduser().resolve()
    if not target.is_file():
        raise FileNotFoundError(target)
    value = json.loads(target.read_text())
    if not isinstance(value, dict):
        raise ValueError(f"JSON object required: {target}")
    return value


def _manifest_from_args(args: dict[str, Any]) -> tuple[dict[str, Any], Path | None]:
    if isinstance(args.get("manifest"), dict):
        return dict(args["manifest"]), None
    if args.get("manifest_path"):
        path = Path(str(args["manifest_path"])).expanduser().resolve()
        return _load_json(path), path
    project = Path(str(args.get("project") or ".")).expanduser().resolve()
    target_dir = Path(str(args.get("target_dir") or project / "dbt" / "target")).expanduser().resolve()
    path = target_dir / "manifest.json"
    return _load_json(path), path


def _node_map(manifest: dict[str, Any]) -> dict[str, dict[str, Any]]:
    result: dict[str, dict[str, Any]] = {}
    for key in ("nodes", "sources", "exposures", "metrics", "semantic_models", "saved_queries"):
        result.update(manifest.get(key, {}) or {})
    return result


def _downstream(manifest: dict[str, Any], starts: Iterable[str]) -> set[str]:
    child_map = manifest.get("child_map", {}) or {}
    seen: set[str] = set()
    queue = deque(starts)
    while queue:
        node = queue.popleft()
        for child in child_map.get(node, ()):
            if child not in seen:
                seen.add(child)
                queue.append(child)
    return seen


def _fingerprint(value: Any) -> str:
    payload = json.dumps(value, sort_keys=True, default=str, separators=(",", ":"))
    return hashlib.sha256(payload.encode()).hexdigest()[:16]


def engine_readiness(args: dict[str, Any]) -> dict[str, Any]:
    """Report dbt runtime readiness without assuming proprietary Fusion availability."""
    override = str(args.get("version_output") or "").strip()
    executable = str(args.get("executable") or "dbt")
    resolved = shutil.which(executable)
    output = override
    status = "PASS" if override else "UNAVAILABLE"
    if not output and resolved:
        try:
            completed = subprocess.run(
                [resolved, "--version"], capture_output=True, text=True, timeout=10, check=False
            )
            output = (completed.stdout or completed.stderr).strip()
            status = "PASS" if completed.returncode == 0 else "WARN"
        except (OSError, subprocess.SubprocessError) as exc:
            output = str(exc)
            status = "WARN"
    lowered = output.casefold()
    engine = "dbt-v2-or-fusion" if "fusion" in lowered or re.search(r"\b2\.\d", lowered) else "dbt-core-compatible"
    return {
        "status": status,
        "executable": resolved or executable,
        "version_output": output,
        "engine_family": engine,
        "sql_aware_capabilities": [
            "manifest-state-diff", "column-aware-review", "lineage-impact", "governed-selective-build"
        ],
        "note": "ADE uses public dbt artifacts/runtime contracts; proprietary dbt services are optional integrations.",
    }


def state_plan(args: dict[str, Any]) -> dict[str, Any]:
    """Compute BUILD/SKIP/CLONE/DEFER candidates from two dbt manifests."""
    current, current_path = _manifest_from_args(args)
    if isinstance(args.get("previous_manifest"), dict):
        previous = dict(args["previous_manifest"])
        previous_path = None
    else:
        raw = args.get("previous_manifest_path") or args.get("state_manifest_path")
        if not raw:
            raise ValueError("state planning requires previous_manifest or previous_manifest_path")
        previous_path = Path(str(raw)).expanduser().resolve()
        previous = _load_json(previous_path)

    old_nodes = _node_map(previous)
    new_nodes = _node_map(current)
    changed = set(get_changed_nodes(previous, current))
    added = set(new_nodes) - set(old_nodes)
    removed = set(old_nodes) - set(new_nodes)
    impacted = _downstream(current, changed | added)
    executable = {
        node_id for node_id, node in new_nodes.items()
        if node.get("resource_type") in {"model", "seed", "snapshot"}
    }
    build = sorted((changed | added | impacted) & executable)
    unchanged = sorted(executable - set(build))

    clone_available = {str(x) for x in args.get("clone_available") or []}
    defer_available = {str(x) for x in args.get("defer_available") or []}
    clone = sorted(set(unchanged) & clone_available)
    defer = sorted((set(unchanged) - set(clone)) & defer_available)
    skip = sorted(set(unchanged) - set(clone) - set(defer))

    actions = []
    for action, items in (("BUILD", build), ("CLONE", clone), ("DEFER", defer), ("SKIP", skip)):
        actions.extend({"node": node, "action": action} for node in items)
    actions.extend({"node": node, "action": "REMOVED_REVIEW"} for node in sorted(removed))
    return {
        "status": "PASS",
        "planner": "ADE_STATE_V1",
        "current_manifest": str(current_path) if current_path else "inline",
        "previous_manifest": str(previous_path) if previous_path else "inline",
        "changed_nodes": sorted(changed),
        "added_nodes": sorted(added),
        "removed_nodes": sorted(removed),
        "counts": {"build": len(build), "clone": len(clone), "defer": len(defer), "skip": len(skip)},
        "actions": actions,
        "selector": " ".join(new_nodes[n].get("name", n) for n in build if n in new_nodes),
        "selectors": {
            "build": [str(new_nodes[n].get("name") or n) for n in build if n in new_nodes],
            "clone": [str(new_nodes[n].get("name") or n) for n in clone if n in new_nodes],
            "defer": [str(new_nodes[n].get("name") or n) for n in defer if n in new_nodes],
            "skip": [str(new_nodes[n].get("name") or n) for n in skip if n in new_nodes],
        },
        "fingerprint": _fingerprint(actions),
    }


def state_execution_contract(args: dict[str, Any]) -> dict[str, Any]:
    """Compile a state plan into deterministic dbt CLI commands without executing them."""
    plan = dict(args["plan"]) if isinstance(args.get("plan"), dict) else state_plan(args)
    selectors = dict(plan.get("selectors") or {})
    if not selectors:
        by_action: dict[str, list[str]] = {"build": [], "clone": [], "defer": [], "skip": []}
        for item in plan.get("actions") or []:
            action = str(item.get("action") or "").casefold()
            if action in by_action:
                by_action[action].append(str(item.get("node") or ""))
        selectors = by_action

    project_dir = Path(str(args.get("project_dir") or args.get("project") or ".")).expanduser().resolve()
    executable = str(args.get("executable") or "dbt")
    state_dir_raw = args.get("state_dir")
    if not state_dir_raw:
        previous = args.get("previous_manifest_path") or args.get("state_manifest_path")
        if previous:
            state_dir_raw = str(Path(str(previous)).expanduser().resolve().parent)
    state_dir = str(Path(str(state_dir_raw)).expanduser().resolve()) if state_dir_raw else ""

    build = [str(item) for item in selectors.get("build") or [] if str(item)]
    clone = [str(item) for item in selectors.get("clone") or [] if str(item)]
    defer = [str(item) for item in selectors.get("defer") or [] if str(item)]
    skip = [str(item) for item in selectors.get("skip") or [] if str(item)]
    if (clone or defer) and not state_dir:
        raise ValueError("state_dir or previous_manifest_path is required for CLONE/DEFER execution contracts")

    commands: list[dict[str, Any]] = []
    if clone:
        commands.append({
            "phase": "clone",
            "argv": [executable, "clone", "--project-dir", str(project_dir), "--state", state_dir, "--select", " ".join(clone)],
            "selectors": clone,
        })
    if build:
        argv = [executable, "build", "--project-dir", str(project_dir), "--select", " ".join(build)]
        if defer:
            argv.extend(["--defer", "--state", state_dir])
        commands.append({"phase": "build", "argv": argv, "selectors": build, "defer_selectors": defer})

    payload = {
        "plan_fingerprint": str(plan.get("fingerprint") or ""),
        "project_dir": str(project_dir),
        "state_dir": state_dir or None,
        "commands": commands,
        "skipped_selectors": skip,
        "deferred_selectors": defer,
    }
    return {
        "status": "PLAN",
        **payload,
        "fingerprint": _fingerprint(payload),
        "mutation_policy": "Dry-run by default. Live execution requires the exact contract fingerprint and ADE mutation approval.",
    }


def state_execute(args: dict[str, Any]) -> dict[str, Any]:
    """Execute a fingerprint-approved state contract without shell interpolation."""
    contract = state_execution_contract(args)
    if bool(args.get("dry_run", True)):
        return {**contract, "status": "DRY_RUN", "executed": False, "results": []}

    approved = str(args.get("approved_fingerprint") or "")
    if not approved or approved != contract["fingerprint"]:
        raise ValueError("live state execution requires approved_fingerprint matching the exact execution contract")

    executable = str(args.get("executable") or "dbt")
    resolved = shutil.which(executable)
    if not resolved:
        return {**contract, "status": "SKIP_EXTERNAL", "executed": False, "reason": f"dbt executable not found: {executable}", "results": []}

    timeout = max(1, min(int(args.get("timeout_seconds", 1800)), 7200))
    results: list[dict[str, Any]] = []
    for command in contract["commands"]:
        argv = list(command["argv"])
        argv[0] = resolved
        completed = subprocess.run(
            argv,
            cwd=contract["project_dir"],
            capture_output=True,
            text=True,
            timeout=timeout,
            check=False,
        )
        item = {
            "phase": command["phase"],
            "argv": argv,
            "returncode": completed.returncode,
            "stdout": (completed.stdout or "")[-20000:],
            "stderr": (completed.stderr or "")[-20000:],
        }
        results.append(item)
        if completed.returncode != 0:
            return {**contract, "status": "FAIL", "executed": True, "results": results}
    return {**contract, "status": "PASS", "executed": bool(contract["commands"]), "results": results}


def _manifest_summary(manifest: dict[str, Any]) -> dict[str, Any]:
    graph = DbtManifestGraph(DbtArtifacts(manifest=manifest))
    summary = graph.summary()
    nodes = _node_map(manifest)
    return {
        **summary,
        "models": [
            {"unique_id": node_id, "name": node.get("name"), "description": node.get("description") or ""}
            for node_id, node in nodes.items() if node.get("resource_type") == "model"
        ],
        "metrics": [
            {"unique_id": node_id, "name": node.get("name"), "description": node.get("description") or ""}
            for node_id, node in nodes.items() if node.get("resource_type") == "metric"
        ],
        "semantic_models": [
            {"unique_id": node_id, "name": node.get("name"), "description": node.get("description") or ""}
            for node_id, node in nodes.items() if node.get("resource_type") == "semantic_model"
        ],
    }


def context_bundle(args: dict[str, Any]) -> dict[str, Any]:
    """Combine structured dbt/semantic metadata with bounded unstructured context."""
    manifest, manifest_path = _manifest_from_args(args)
    project = Path(str(args.get("project") or ".")).expanduser().resolve()
    documents = []
    for raw in args.get("documents") or []:
        path = Path(str(raw)).expanduser()
        if not path.is_absolute():
            path = (project / path).resolve()
        if not path.is_file():
            continue
        text = path.read_text(errors="replace")
        documents.append({"path": str(path), "text": text[: int(args.get("document_char_limit", 12000))]})

    semantic_resources: list[dict[str, Any]] = []
    semantic_db = args.get("semantic_database")
    if semantic_db:
        registry = SemanticRegistry(semantic_db)
        semantic_resources = [registry.show(item["resource_id"]) for item in registry.list()]

    records = []
    for index, raw in enumerate(args.get("records") or []):
        if not isinstance(raw, dict):
            continue
        text = str(raw.get("text") or raw.get("content") or "")
        if not text:
            continue
        records.append({
            "id": str(raw.get("id") or f"record-{index + 1}"),
            "source": str(raw.get("source") or raw.get("provider") or "external"),
            "type": str(raw.get("type") or "text"),
            "text": text[: int(args.get("record_char_limit", 12000))],
            "metadata": dict(raw.get("metadata") or {}),
        })

    payload = {
        "dbt": _manifest_summary(manifest),
        "semantic_resources": semantic_resources,
        "documents": documents,
        "records": records,
    }
    return {
        "status": "PASS",
        "source": str(manifest_path) if manifest_path else "inline-manifest",
        "bundle": payload,
        "counts": {
            "models": len(payload["dbt"]["models"]),
            "metrics": len(payload["dbt"]["metrics"]),
            "semantic_models": len(payload["dbt"]["semantic_models"]),
            "semantic_resources": len(semantic_resources),
            "documents": len(documents),
            "records": len(records),
        },
        "fingerprint": _fingerprint(payload),
    }


def _terms(text: str) -> set[str]:
    # Split qualified identifiers (for example model.package.fact_orders) into
    # searchable components while retaining ordinary words and short dbt names.
    return {
        token.casefold()
        for token in re.findall(r"[A-Za-z0-9_]+", text)
        if token
    }


def context_search(args: dict[str, Any]) -> dict[str, Any]:
    query = str(args.get("query") or "").strip()
    if not query:
        raise ValueError("context search requires query")
    bundle = args.get("bundle") if isinstance(args.get("bundle"), dict) else context_bundle(args)["bundle"]
    q = _terms(query)
    hits: list[dict[str, Any]] = []

    dbt = bundle.get("dbt", {})
    for kind in ("models", "metrics", "semantic_models"):
        for item in dbt.get(kind, []):
            text = " ".join(str(item.get(k) or "") for k in ("unique_id", "name", "description"))
            score = len(q & _terms(text))
            if score:
                hits.append({"score": score, "source": f"dbt:{kind}", **item})
    for resource in bundle.get("semantic_resources", []):
        for item in resource.get("elements", []):
            text = " ".join(str(item.get(k) or "") for k in ("kind", "name", "parent", "description", "expression"))
            score = len(q & _terms(text))
            if score:
                hits.append({"score": score, "source": f"semantic:{resource.get('name')}", **item})
    for document in bundle.get("documents", []):
        text = str(document.get("text") or "")
        score = len(q & _terms(text[:50000]))
        if score:
            hits.append({"score": score, "source": "document", "path": document.get("path"), "excerpt": text[:1000]})
    for record in bundle.get("records", []):
        text = str(record.get("text") or "")
        score = len(q & _terms(text[:50000]))
        if score:
            hits.append({
                "score": score,
                "source": f"record:{record.get('source') or 'external'}",
                "record_id": record.get("id"),
                "record_type": record.get("type"),
                "metadata": record.get("metadata") or {},
                "excerpt": text[:1000],
            })
    hits.sort(key=lambda x: (-int(x["score"]), str(x.get("name") or x.get("path") or x.get("record_id") or "")))
    limit = max(1, min(int(args.get("limit", 20)), 100))
    return {"status": "PASS", "query": query, "count": min(len(hits), limit), "results": hits[:limit]}


def wizard_plan(args: dict[str, Any]) -> dict[str, Any]:
    """Project-aware deterministic planning surface analogous to an analytics coding agent."""
    question = str(args.get("question") or "").strip()
    if not question:
        raise ValueError("wizard planning requires question")
    search = context_search({**args, "query": question, "limit": int(args.get("limit", 12))})
    q = question.casefold()
    intents = []
    if any(word in q for word in ("depend", "downstream", "impact", "lineage")):
        intents.append("lineage-impact")
    if any(word in q for word in ("chart", "dashboard", "visual")):
        intents.append("bi-as-code")
    if any(word in q for word in ("cost", "rebuild", "state", "changed", "skip")):
        intents.append("state-optimization")
    if any(word in q for word in ("metric", "revenue", "count", "trend", "compare", " by ")):
        intents.append("semantic-explore")
    if not intents:
        intents.append("project-context")
    tools = {
        "lineage-impact": ["dbt_lineage", "dbt_impact"],
        "bi-as-code": ["dbt_next_chart_validate", "dbt_next_chart_compile"],
        "state-optimization": ["dbt_next_state_plan"],
        "semantic-explore": ["dbt_next_explore_plan", "semantic_verified_search"],
        "project-context": ["dbt_next_context_search"],
    }
    ordered_tools: list[str] = []
    for intent in intents:
        for tool in tools[intent]:
            if tool not in ordered_tools:
                ordered_tools.append(tool)
    return {
        "status": "PASS",
        "mode": "DETERMINISTIC_PROJECT_AGENT",
        "question": question,
        "intents": intents,
        "recommended_tools": ordered_tools,
        "context_hits": search["results"],
        "requires_llm": False,
        "next_step": "Invoke the recommended governed tools; mutation remains separately approval-gated.",
    }


def explore_plan(args: dict[str, Any]) -> dict[str, Any]:
    """Ground a business question in semantic metadata and return a governed query plan."""
    question = str(args.get("question") or "").strip()
    if not question:
        raise ValueError("explore requires question")
    semantic_db = args.get("semantic_database")
    if not semantic_db:
        raise ValueError("explore requires semantic_database")
    registry = SemanticRegistry(semantic_db)
    matches = registry.search(question, limit=int(args.get("limit", 25)))
    verified = registry.find_verified(question, limit=int(args.get("verified_limit", 5)))
    metrics = [item for item in matches if "metric" in str(item.get("kind", "")) or item.get("kind") == "fact"]
    dimensions = [item for item in matches if item.get("kind") in {"dimension", "time_dimension"}]
    confidence = min(1.0, (len(metrics) * 0.25) + (len(dimensions) * 0.1) + (len(verified) * 0.35))
    status = "READY" if metrics and confidence >= 0.35 else "NEEDS_CLARIFICATION"
    return {
        "status": status,
        "question": question,
        "metrics": metrics[:8],
        "dimensions": dimensions[:12],
        "verified_queries": verified,
        "confidence": round(confidence, 3),
        "execution_policy": "Generate/execute SQL only after semantic selection is unambiguous or a verified query matches.",
    }


def _load_yaml_value(args: dict[str, Any]) -> tuple[dict[str, Any], str]:
    if isinstance(args.get("spec"), dict):
        return dict(args["spec"]), "inline"
    if args.get("yaml"):
        value = yaml.safe_load(str(args["yaml"])) or {}
        if not isinstance(value, dict):
            raise ValueError("chart YAML must decode to an object")
        return value, "inline-yaml"
    if args.get("path"):
        path = Path(str(args["path"])).expanduser().resolve()
        value = yaml.safe_load(path.read_text()) or {}
        if not isinstance(value, dict):
            raise ValueError("chart YAML must decode to an object")
        return value, str(path)
    raise ValueError("chart operation requires spec, yaml, or path")


def chart_validate(args: dict[str, Any]) -> dict[str, Any]:
    spec, source = _load_yaml_value(args)
    dashboard = spec.get("dashboard") if isinstance(spec.get("dashboard"), dict) else spec
    errors: list[str] = []
    warnings: list[str] = []
    name = dashboard.get("name")
    charts = dashboard.get("charts") or []
    if not isinstance(name, str) or not name.strip():
        errors.append("dashboard.name is required")
    if not isinstance(charts, list) or not charts:
        errors.append("dashboard.charts must contain at least one chart")
        charts = []
    normalized = []
    seen: set[str] = set()
    for index, chart in enumerate(charts):
        if not isinstance(chart, dict):
            errors.append(f"charts[{index}] must be an object")
            continue
        chart_name = str(chart.get("name") or f"chart_{index+1}")
        if chart_name in seen:
            errors.append(f"duplicate chart name: {chart_name}")
        seen.add(chart_name)
        metric = chart.get("metric") or chart.get("metrics")
        sql = chart.get("sql")
        if not metric and not sql:
            errors.append(f"chart {chart_name} requires metric(s) or sql")
        if sql and not _READ_ONLY_SQL.match(str(sql)):
            errors.append(f"chart {chart_name} SQL must be read-only")
        normalized.append({
            "name": chart_name,
            "type": str(chart.get("type") or "table"),
            "metrics": metric if isinstance(metric, list) else [metric] if metric else [],
            "dimensions": chart.get("dimensions") or ([chart.get("dimension")] if chart.get("dimension") else []),
            "sql": sql,
            "title": chart.get("title") or chart_name.replace("_", " ").title(),
        })
    if not dashboard.get("description"):
        warnings.append("dashboard.description is recommended for governed discovery")
    return {
        "status": "FAIL" if errors else "PASS",
        "source": source,
        "dashboard": str(name or ""),
        "errors": errors,
        "warnings": warnings,
        "charts": normalized,
        "fingerprint": _fingerprint({"dashboard": name, "charts": normalized}),
    }


def chart_compile(args: dict[str, Any]) -> dict[str, Any]:
    validated = chart_validate(args)
    if validated["status"] != "PASS":
        return validated
    compiled = {
        "dashboard": validated["dashboard"],
        "charts": [
            {
                **chart,
                "query_contract": {
                    "metrics": chart["metrics"],
                    "group_by": chart["dimensions"],
                    "sql": chart["sql"],
                },
            }
            for chart in validated["charts"]
        ],
        "targets": ["ade-web", "power-bi-contract", "excel-contract", "ai-agent-contract"],
    }
    return {"status": "PASS", "compiled": compiled, "fingerprint": _fingerprint(compiled)}


def model_compute_plan(args: dict[str, Any]) -> dict[str, Any]:
    """Route dbt models to warehouse or local lake compute while preserving ref dependencies."""
    manifest, manifest_path = _manifest_from_args(args)
    nodes = _node_map(manifest)
    overrides = {str(k): str(v).casefold() for k, v in dict(args.get("model_engines") or {}).items()}
    default_engine = str(args.get("default_engine") or "warehouse").casefold()
    if default_engine not in {"warehouse", "lake"}:
        raise ValueError("default_engine must be warehouse or lake")

    assignments: dict[str, str] = {}
    for node_id, node in nodes.items():
        if node.get("resource_type") != "model":
            continue
        name = str(node.get("name") or node_id)
        meta = node.get("config", {}).get("meta", {}) or node.get("meta", {}) or {}
        requested = overrides.get(node_id) or overrides.get(name) or str(meta.get("ade_compute") or default_engine).casefold()
        if requested in {"duckdb", "iceberg", "lake-compute"}:
            requested = "lake"
        if requested not in {"warehouse", "lake"}:
            raise ValueError(f"unsupported compute engine for {name}: {requested}")
        assignments[node_id] = requested

    boundaries = []
    for node_id, engine in assignments.items():
        node = nodes[node_id]
        for parent in node.get("depends_on", {}).get("nodes", ()):
            parent_engine = assignments.get(parent)
            if parent_engine and parent_engine != engine:
                boundaries.append({
                    "upstream": parent,
                    "upstream_engine": parent_engine,
                    "downstream": node_id,
                    "downstream_engine": engine,
                    "contract": "materialized-relation-boundary",
                })

    models = []
    for node_id in sorted(assignments):
        node = nodes[node_id]
        engine = assignments[node_id]
        models.append({
            "unique_id": node_id,
            "name": node.get("name"),
            "engine": engine,
            "depends_on": list(node.get("depends_on", {}).get("nodes", ())),
            "execution": "warehouse-dbt" if engine == "warehouse" else "duckdb-lake",
            "ref_contract": "preserved-via-materialized-relation",
        })
    return {
        "status": "PASS",
        "manifest": str(manifest_path) if manifest_path else "inline",
        "default_engine": default_engine,
        "counts": {
            "models": len(models),
            "warehouse": sum(item["engine"] == "warehouse" for item in models),
            "lake": sum(item["engine"] == "lake" for item in models),
            "cross_engine_boundaries": len(boundaries),
        },
        "models": models,
        "cross_engine_boundaries": boundaries,
        "fingerprint": _fingerprint({"models": models, "boundaries": boundaries}),
        "note": "Cross-engine refs require upstream materialization into a relation visible to the downstream engine; ADE does not claim zero-copy interoperability.",
    }


def lake_compute_plan(args: dict[str, Any]) -> dict[str, Any]:
    source = str(args.get("source") or "").strip()
    if not source:
        raise ValueError("lake compute requires source")
    source_type = str(args.get("source_type") or "auto").casefold()
    if source_type == "auto":
        lowered = source.casefold()
        source_type = "iceberg" if lowered.startswith(("s3://", "gs://", "azure://")) or "iceberg" in lowered else "parquet"
    if source_type not in {"parquet", "iceberg"}:
        raise ValueError("source_type must be parquet, iceberg, or auto")
    escaped = source.replace("'", "''")
    scan = f"iceberg_scan('{escaped}')" if source_type == "iceberg" else f"read_parquet('{escaped}')"
    sql = str(args.get("sql") or f"SELECT * FROM {scan} LIMIT {int(args.get('limit', 100))}")
    if not _READ_ONLY_SQL.match(sql):
        raise ValueError("lake compute accepts read-only SQL only")
    return {
        "status": "PLAN",
        "engine": "duckdb",
        "source_type": source_type,
        "source": source,
        "sql": sql,
        "extensions": ["iceberg"] if source_type == "iceberg" else [],
        "note": "Iceberg execution requires a locally available DuckDB iceberg extension; no extension installation is attempted automatically.",
    }


def lake_compute_run(args: dict[str, Any]) -> dict[str, Any]:
    plan = lake_compute_plan(args)
    try:
        import duckdb  # type: ignore
    except ImportError:
        return {**plan, "status": "SKIP_EXTERNAL", "reason": "duckdb is not installed"}
    connection = duckdb.connect(str(args.get("database") or ":memory:"))
    if plan["source_type"] == "iceberg":
        try:
            connection.execute("LOAD iceberg")
        except Exception as exc:
            return {**plan, "status": "SKIP_EXTERNAL", "reason": f"DuckDB iceberg extension unavailable: {exc}"}
    try:
        cursor = connection.execute(plan["sql"])
        columns = [item[0] for item in cursor.description or []]
        rows = [dict(zip(columns, row)) for row in cursor.fetchmany(max(1, min(int(args.get("row_limit", 200)), 1000)))]
        return {**plan, "status": "PASS", "columns": columns, "rows": rows, "row_count": len(rows)}
    except Exception as exc:
        return {**plan, "status": "FAIL", "error": str(exc)}
    finally:
        connection.close()


def agents_schema(args: dict[str, Any] | None = None) -> dict[str, Any]:
    """Export a small open contract that AI/MCP clients can consume."""
    return {
        "status": "PASS",
        "schema_version": "ade-agents/1.0",
        "resources": [
            {"name": "dbt_project_context", "tool": "dbt_next_context_bundle", "read_only": True},
            {"name": "semantic_explore", "tool": "dbt_next_explore_plan", "read_only": True},
            {"name": "bi_as_code", "tool": "dbt_next_chart_compile", "read_only": True},
            {"name": "state_plan", "tool": "dbt_next_state_plan", "read_only": True},
            {"name": "model_compute_plan", "tool": "dbt_next_model_compute_plan", "read_only": True},
            {"name": "lake_compute", "tool": "dbt_next_lake_compute_run", "read_only": True},
        ],
        "principles": [
            "evidence-first", "semantic-grounding", "read-only-by-default", "approval-gated-mutation", "provider-neutral"
        ],
    }
