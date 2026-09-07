"""Deterministic repository discovery for data-engineering projects."""

from __future__ import annotations

import ast
import json
import os
import re
from collections import Counter
from pathlib import Path
from typing import Any

from agentic_data_platform.dbt.manifest_graph import DbtArtifacts, DbtManifestGraph
from agentic_data_platform.platform.airflow import AirflowProject


_SKIP_PARTS = {
    ".git", ".venv", "venv", "node_modules", "__pycache__", ".pytest_cache",
    ".ruff_cache", "logs", "dbt_packages", "backend", "source_exports", "generated",
}
_CREATE_OBJECT = re.compile(
    r"(?im)^\s*CREATE\s+(?:OR\s+REPLACE\s+)?(DATABASE|SCHEMA|WAREHOUSE|FILE\s+FORMAT|STAGE|TABLE|STREAM|ROLE)\b"
)
_CREATE_TABLE = re.compile(r"(?im)^\s*CREATE\s+TABLE(?:\s+IF\s+NOT\s+EXISTS)?\s+[^\s(]+")


def _read_json(path: Path) -> dict[str, Any] | None:
    try:
        return json.loads(path.read_text(encoding="utf-8")) if path.is_file() else None
    except (OSError, json.JSONDecodeError):
        return None


def _usable(path: Path) -> bool:
    return not any(part in _SKIP_PARTS for part in path.parts)


def _find_files(root: Path, name: str) -> list[Path]:
    return sorted(path for path in root.rglob(name) if path.is_file() and _usable(path))


def _preferred(paths: list[Path], marker: str) -> Path | None:
    if not paths:
        return None
    return sorted(paths, key=lambda item: (marker not in str(item).lower(), len(item.parts), str(item)))[0]


def _count_tables(path: Path | None) -> int:
    return len(_CREATE_TABLE.findall(path.read_text(encoding="utf-8"))) if path and path.is_file() else 0


def _file_feed_count(path: Path | None) -> int:
    if not path or not path.is_file():
        return 0
    try:
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    except SyntaxError:
        return 0
    for node in tree.body:
        value = node.value if isinstance(node, (ast.Assign, ast.AnnAssign)) else None
        names: list[str] = []
        if isinstance(node, ast.Assign):
            names = [item.id for item in node.targets if isinstance(item, ast.Name)]
        elif isinstance(node, ast.AnnAssign) and isinstance(node.target, ast.Name):
            names = [node.target.id]
        if "FEEDS" in names and isinstance(value, ast.Dict):
            return len(value.keys)
    return 0


class PlatformDiscovery:
    """Inspect a project using files and build artifacts, never model-generated counts."""

    def __init__(self, project: str | Path) -> None:
        self.root = Path(project).expanduser().resolve()
        if not self.root.is_dir():
            raise FileNotFoundError(f"project directory not found: {self.root}")

    def _hospitality_root(self) -> Path:
        if (self.root / "dbt" / "dbt_project.yml").is_file():
            return self.root
        candidate = self.root / "hospitality-snowflake-data-platform"
        if (candidate / "dbt" / "dbt_project.yml").is_file():
            return candidate
        projects = _find_files(self.root, "dbt_project.yml")
        selected = _preferred(projects, "hospitality")
        return selected.parent.parent if selected and selected.parent.name == "dbt" else (selected.parent if selected else self.root)

    def _dbt(self, project: Path) -> dict[str, Any]:
        project_file = project / "dbt" / "dbt_project.yml"
        if not project_file.is_file():
            project_file = _preferred(_find_files(project, "dbt_project.yml"), "hospitality") or project_file
        dbt_root = project_file.parent
        manifest_path = dbt_root / "target" / "manifest.json"
        manifest = _read_json(manifest_path)
        if manifest:
            graph = DbtManifestGraph(DbtArtifacts.load(manifest_path.parent))
            counts = graph.summary()["resource_counts"]
            return {
                "found": True, "project_dir": str(dbt_root), "manifest": str(manifest_path),
                "manifest_found": True, "models": counts.get("model", 0), "sources": counts.get("source", 0),
                "tests": counts.get("test", 0), "snapshots": counts.get("snapshot", 0),
                "exposures": counts.get("exposure", 0), "metrics": counts.get("metric", 0),
            }
        models = list((dbt_root / "models").rglob("*.sql")) if (dbt_root / "models").is_dir() else []
        snapshots = list((dbt_root / "snapshots").rglob("*.sql")) if (dbt_root / "snapshots").is_dir() else []
        return {
            "found": project_file.is_file(), "project_dir": str(dbt_root), "manifest": str(manifest_path),
            "manifest_found": False, "models": len(models), "sources": 0, "tests": 0, "snapshots": len(snapshots),
            "exposures": 0, "metrics": 0,
        }

    def _sources(self, project: Path) -> dict[str, Any]:
        oracle = project / "sources" / "oracle" / "ddl" / "001_source_schema.sql"
        postgres = project / "sources" / "postgres" / "ddl" / "001_source_schema.sql"
        generator = project / "data_generator" / "generate_file_data.py"
        return {
            "oracle": oracle.is_file(), "oracle_tables": _count_tables(oracle),
            "postgres": postgres.is_file(), "postgres_tables": _count_tables(postgres),
            "files": generator.is_file(), "file_feeds": _file_feed_count(generator),
        }

    def _snowflake(self, project: Path) -> dict[str, Any]:
        root = project / "snowflake"
        files = sorted(root.rglob("*.sql")) if root.is_dir() else []
        counts: Counter[str] = Counter()
        for path in files:
            for match in _CREATE_OBJECT.finditer(path.read_text(encoding="utf-8")):
                counts[match.group(1).lower().replace(" ", "_")] += 1
        credential_keys = ("SNOWFLAKE_ACCOUNT", "SNOWFLAKE_USER", "SNOWFLAKE_PASSWORD")
        live = all(os.getenv(key) for key in credential_keys)
        return {
            "found": bool(files), "static_config": bool(files), "ddl_files": len(files),
            "object_count": sum(counts.values()), "objects": dict(sorted(counts.items())),
            "live": live, "live_status": "AVAILABLE" if live else "SKIPPED - Snowflake credentials unavailable",
        }

    def inventory(self) -> dict[str, Any]:
        project = self._hospitality_root()
        airflow_root = project / "airflow" / "dags"
        airflow = AirflowProject.scan(project) if airflow_root.is_dir() else AirflowProject()
        program_root = self.root if (self.root / "shiftforge").exists() else self.root.parent
        workflows = program_root / ".github" / "workflows"
        ci_files = [path for path in workflows.glob("*.y*ml")] if workflows.is_dir() else []
        shiftforge = program_root / "shiftforge"
        ldh = program_root / "local-data-harness"
        return {
            "mode": "STATIC_LOCAL",
            "project": str(self.root),
            "hospitality_project": str(project),
            "dbt": self._dbt(project),
            "airflow": {"found": airflow_root.is_dir(), **airflow.summary()},
            "snowflake": self._snowflake(project),
            "sources": self._sources(project),
            "docker": {
                "found": any(project.glob("docker-compose*.yml")) or (project / "Dockerfile").is_file(),
                "compose_files": [str(path) for path in sorted(project.glob("docker-compose*.yml"))],
            },
            "ci_cd": {"found": bool(ci_files), "workflow_files": [str(path) for path in sorted(ci_files)]},
            "shiftforge": {"found": (shiftforge / "pyproject.toml").is_file(), "path": str(shiftforge)},
            "local_data_harness": {"found": (ldh / "package.json").is_file(), "path": str(ldh)},
        }

    def discover(self) -> dict[str, Any]:
        result = self.inventory()
        result["components_found"] = sorted(
            name for name in ("dbt", "airflow", "snowflake", "docker", "ci_cd", "shiftforge", "local_data_harness")
            if result[name].get("found")
        )
        return result

    def health(self) -> dict[str, Any]:
        inventory = self.inventory()
        checks = {
            "project": {"status": "PASS", "detail": str(self.root)},
            "dbt_project": {"status": "PASS" if inventory["dbt"]["found"] else "FAIL", "detail": inventory["dbt"]["project_dir"]},
            "dbt_manifest": {"status": "PASS" if inventory["dbt"]["manifest_found"] else "WARN", "detail": inventory["dbt"]["manifest"]},
            "airflow_static": {"status": "PASS" if inventory["airflow"]["found"] and not inventory["airflow"]["parse_errors"] else "FAIL", "detail": f"{inventory['airflow']['dag_count']} DAGs"},
            "snowflake_static": {"status": "PASS" if inventory["snowflake"]["static_config"] else "WARN", "detail": f"{inventory['snowflake']['object_count']} objects"},
            "snowflake_live": {"status": "PASS" if inventory["snowflake"]["live"] else "SKIP", "detail": inventory["snowflake"]["live_status"]},
            "oracle_live": {"status": "SKIP", "detail": "Oracle service/client not required in local mode"},
        }
        overall = "FAIL" if any(item["status"] == "FAIL" for item in checks.values()) else "PASS"
        return {"mode": "STATIC_LOCAL", "status": overall, "checks": checks, "inventory": inventory}
