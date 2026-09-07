"""Captures dependency-graph snapshots for a dbt project or an Airflow DAG,
as {"nodes": [...], "edges": [...]} JSON the UI can render as a simple graph.
"""

from __future__ import annotations

import json
import subprocess
from pathlib import Path

from .airflow_client import AirflowClient


def refresh_dbt_lineage(dbt_bin: str, project_dir: str, profiles_dir: str, target: str = "dev") -> dict:
    """`dbt parse` compiles the manifest without touching the warehouse, so
    this is safe/cheap to call right after project creation and before any
    real run."""
    subprocess.run(
        [
            dbt_bin, "parse",
            "--project-dir", project_dir,
            "--profiles-dir", profiles_dir,
            "--target", target,
            "--no-use-colors",
        ],
        cwd=project_dir,
        capture_output=True,
        text=True,
        timeout=120,
    )  # a parse error still leaves a usable manifest.json from the last good parse, if any

    manifest_path = Path(project_dir) / "target" / "manifest.json"
    if not manifest_path.exists():
        return {"nodes": [], "edges": []}

    manifest = json.loads(manifest_path.read_text())
    nodes = []
    edges = []
    all_nodes = {**manifest.get("nodes", {}), **manifest.get("sources", {})}
    for unique_id, node in all_nodes.items():
        nodes.append(
            {
                "id": unique_id,
                "label": node.get("name", unique_id),
                "kind": node.get("resource_type", "unknown"),
            }
        )
    for unique_id, node in manifest.get("nodes", {}).items():
        for dep in node.get("depends_on", {}).get("nodes", []):
            edges.append({"from": dep, "to": unique_id})

    return {"nodes": nodes, "edges": edges}


def refresh_airflow_dag_lineage(client: AirflowClient, dag_id: str) -> dict:
    tasks = client.get_dag_tasks(dag_id)
    nodes = [{"id": t["task_id"], "label": t["task_id"], "kind": t.get("task_type", "task")} for t in tasks]
    edges = []
    for t in tasks:
        for downstream in t.get("downstream_task_ids", []) or []:
            edges.append({"from": t["task_id"], "to": downstream})
    return {"nodes": nodes, "edges": edges}
