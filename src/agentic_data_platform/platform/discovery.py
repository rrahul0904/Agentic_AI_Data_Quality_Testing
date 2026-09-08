"""Deterministic repository discovery for data-engineering projects."""

from __future__ import annotations

import ast
import importlib.metadata
import json
import os
import re
import shutil
import subprocess
from collections import Counter
from pathlib import Path
from typing import Any

import yaml

from agentic_data_platform.dbt.manifest_graph import DbtArtifacts, DbtManifestGraph
from agentic_data_platform.platform.airflow import AirflowProject
from agentic_data_platform.providers import ProviderRegistry
from agentic_data_platform.skills.service import BUILTIN_SKILLS


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

    @staticmethod
    def _package_version(name: str) -> str | None:
        try:
            return importlib.metadata.version(name)
        except importlib.metadata.PackageNotFoundError:
            return None

    @staticmethod
    def _run(argv: list[str], cwd: Path) -> str | None:
        try:
            completed = subprocess.run(
                argv,
                cwd=cwd,
                capture_output=True,
                text=True,
                check=False,
                timeout=5,
            )
        except (OSError, subprocess.TimeoutExpired):
            return None
        value = (completed.stdout or "").strip()
        return value if completed.returncode == 0 and value else None

    @staticmethod
    def _sanitize_remote(value: str | None) -> str | None:
        if not value:
            return value
        return re.sub(r"(?<=://)[^/@\s]+@", "***@", value)

    def _git(self) -> dict[str, Any]:
        root = self._run(["git", "rev-parse", "--show-toplevel"], self.root)
        if not root:
            return {"found": False, "repository_root": None, "branch": None, "remote": None, "changed_files": []}
        repo_root = Path(root)
        branch = self._run(["git", "branch", "--show-current"], repo_root)
        remote = self._sanitize_remote(self._run(["git", "remote", "get-url", "origin"], repo_root))
        changed = self._run(["git", "status", "--porcelain"], repo_root) or ""
        files = sorted({
            line[3:].strip()
            for line in changed.splitlines()
            if len(line) >= 4 and line[3:].strip()
        })
        return {
            "found": True,
            "repository_root": str(repo_root),
            "branch": branch,
            "remote": remote,
            "changed_files": files,
        }

    def _dbt_discovery(self, project: Path) -> dict[str, Any]:
        base = self._dbt(project)
        dbt_root = Path(base["project_dir"])
        project_file = dbt_root / "dbt_project.yml"
        project_yaml: dict[str, Any] = {}
        diagnostics: list[dict[str, str]] = []
        project_files = _find_files(self.root, "dbt_project.yml")
        if project_file.is_file():
            try:
                project_yaml = yaml.safe_load(project_file.read_text(encoding="utf-8")) or {}
            except OSError:
                diagnostics.append({
                    "code": "DBT_PROJECT_READ_ERROR",
                    "path": str(project_file),
                    "message": "dbt_project.yml could not be read",
                })
            except yaml.YAMLError:
                diagnostics.append({
                    "code": "DBT_PROJECT_YAML_INVALID",
                    "path": str(project_file),
                    "message": "dbt_project.yml is malformed YAML",
                })
        profile_candidates = [dbt_root / "profiles.yml", Path.home() / ".dbt" / "profiles.yml"]
        profile_file = next((item for item in profile_candidates if item.is_file()), None)
        profile_name = project_yaml.get("profile")
        target_name = None
        adapter = None
        if profile_file:
            try:
                raw_profiles = yaml.safe_load(profile_file.read_text(encoding="utf-8")) or {}
                if not isinstance(raw_profiles, dict):
                    raise AttributeError("profiles.yml root must be a mapping")
                if profile_name:
                    profile = raw_profiles.get(profile_name) or {}
                    if not isinstance(profile, dict):
                        raise AttributeError("dbt profile must be a mapping")
                    target_name = profile.get("target")
                    outputs = profile.get("outputs") or {}
                    if not isinstance(outputs, dict):
                        raise AttributeError("dbt profile outputs must be a mapping")
                    target = outputs.get(target_name) or {}
                    if not isinstance(target, dict):
                        raise AttributeError("dbt profile target must be a mapping")
                    adapter = target.get("type")
            except OSError:
                diagnostics.append({
                    "code": "DBT_PROFILES_READ_ERROR",
                    "path": str(profile_file),
                    "message": "profiles.yml could not be read",
                })
            except (yaml.YAMLError, AttributeError):
                diagnostics.append({
                    "code": "DBT_PROFILES_YAML_INVALID",
                    "path": str(profile_file),
                    "message": "profiles.yml is malformed or has an invalid structure",
                })
        files = {
            name: str(path) if path.exists() else None
            for name, path in {
                "dbt_project_yml": project_file,
                "profiles_yml": profile_file or (dbt_root / "profiles.yml"),
                "manifest_json": dbt_root / "target" / "manifest.json",
                "catalog_json": dbt_root / "target" / "catalog.json",
                "run_results_json": dbt_root / "target" / "run_results.json",
                "packages_yml": dbt_root / "packages.yml",
                "dependencies_yml": dbt_root / "dependencies.yml",
                "models": dbt_root / "models",
                "macros": dbt_root / "macros",
                "tests_dir": dbt_root / "tests",
                "seeds": dbt_root / "seeds",
                "snapshots_dir": dbt_root / "snapshots",
            }.items()
        }
        return {
            **base,
            "project_name": project_yaml.get("name"),
            "dbt_version": self._package_version("dbt-core"),
            "profile": profile_name,
            "target": target_name,
            "adapter": adapter,
            "files": files,
            "project_count": len(project_files),
            "projects": [str(item.parent) for item in project_files],
            "diagnostics": diagnostics,
        }

    def _airflow_scan(self, project: Path) -> tuple[AirflowProject, list[Path]]:
        """Scan every repository Airflow root without executing DAG code.

        dbt and Airflow commonly live as siblings in a monorepo. Discovery may
        select a nested dbt project as its primary project root, so Airflow
        discovery must remain repository-scoped rather than dbt-root-scoped.
        """

        candidates = {
            candidate
            for candidate in (project / "airflow" / "dags", self.root / "airflow" / "dags")
            if candidate.is_dir() and _usable(candidate)
        }
        candidates.update(
            path
            for path in self.root.rglob("dags")
            if path.is_dir() and path.parent.name == "airflow" and _usable(path)
        )
        airflow = AirflowProject()
        dag_files: list[Path] = []
        for dags_dir in sorted(candidates, key=str):
            scanned = AirflowProject.scan(dags_dir)
            for dag_id, dag in scanned.dags.items():
                airflow.dags.setdefault(dag_id, dag)
            airflow.parse_errors.extend(scanned.parse_errors)
            dag_files.extend(path for path in dags_dir.rglob("*.py") if _usable(path))
        return airflow, sorted(set(dag_files), key=str)

    def _airflow_discovery(self, project: Path) -> dict[str, Any]:
        airflow, dag_files = self._airflow_scan(project)
        text = "\n".join(
            path.read_text(encoding="utf-8", errors="ignore")
            for path in dag_files
        )
        installed_providers = sorted({
            dist.metadata["Name"]
            for dist in importlib.metadata.distributions()
            if str(dist.metadata.get("Name") or "").startswith("apache-airflow-providers-")
        })
        summary = airflow.summary()
        return {
            "found": bool(dag_files),
            **summary,
            "airflow_home": os.getenv("AIRFLOW_HOME"),
            "airflow_cfg": str(Path(os.getenv("AIRFLOW_HOME", "")) / "airflow.cfg") if os.getenv("AIRFLOW_HOME") else None,
            "version": self._package_version("apache-airflow"),
            "providers": installed_providers,
            "task_sdk_usage": "airflow.sdk" in text,
            "assets_detected": text.count("Asset("),
            "datasets_detected": text.count("Dataset("),
            "dag_folders": sorted({str(path.parent) for path in dag_files}),
        }

    def _sql_tooling(self, dbt: dict[str, Any]) -> dict[str, Any]:
        configs = [
            self.root / ".sqlfluff",
            self.root / "pyproject.toml",
            self.root / "setup.cfg",
            self.root / "tox.ini",
        ]
        dialect = dbt.get("adapter") or (
            "snowflake" if _find_files(self.root, "dbt_project.yml") else None
        )
        return {
            "sqlfluff_available": shutil.which("sqlfluff") is not None,
            "sqlfluff_config": next((str(item) for item in configs if item.is_file()), None),
            "dialect": dialect,
            "sqlglot_compatible": True,
        }

    def _warehouse_hints(self) -> list[dict[str, Any]]:
        hints = {
            "snowflake": ("SNOWFLAKE_ACCOUNT", "ADE_SNOWFLAKE_ACCOUNT"),
            "bigquery": ("GOOGLE_CLOUD_PROJECT", "ADE_BIGQUERY_PROJECT"),
            "databricks": ("DATABRICKS_HOST", "ADE_DATABRICKS_HOST"),
            "postgres": ("DATABASE_URL", "ADE_POSTGRES_DSN"),
            "redshift": ("ADE_REDSHIFT_DSN",),
            "trino": ("ADE_TRINO_HOST",),
            "clickhouse": ("ADE_CLICKHOUSE_HOST",),
            "duckdb": ("DUCKDB_PATH",),
            "mysql": ("ADE_MYSQL_HOST",),
            "sqlserver": ("ADE_SQLSERVER_CONNECTION_STRING",),
            "oracle": ("ADE_ORACLE_DSN",),
            "sqlite": ("ADE_SQLITE_DATABASE",),
            "mongodb": ("ADE_MONGODB_URI",),
        }
        return [
            {
                "warehouse": name,
                "configuration_detected": any(bool(os.getenv(key)) for key in keys),
                "credential_values_exposed": False,
            }
            for name, keys in hints.items()
        ]

    def _agentic(self) -> dict[str, Any]:
        providers = ProviderRegistry().specs()
        mcp_path = self.root / ".altimate-code" / "altimate-code.json"
        mcp = _read_json(mcp_path) or {}
        servers = mcp.get("mcpServers") or mcp.get("mcp_servers") or mcp.get("mcp") or {}
        if not isinstance(servers, dict):
            servers = {}
        installed_skills = [
            path for base in (
                self.root / ".altimate-code" / "skills",
                self.root / ".agents" / "skills",
                self.root / ".claude" / "skills",
            )
            if base.is_dir()
            for path in base.glob("*/SKILL.md")
        ]
        config_candidates = [
            self.root / ".agentic.yml",
            self.root / ".agentic" / "config.yml",
            mcp_path,
        ]
        return {
            "config": next((str(item) for item in config_candidates if item.is_file()), None),
            "project_rules": [str(item) for item in (self.root / ".agentic").glob("*.md")] if (self.root / ".agentic").is_dir() else [],
            "training": {
                "configured": (self.root / ".ade" / "training.db").is_file(),
                "path": str(self.root / ".ade" / "training.db"),
            },
            "skills": {
                "builtin_count": len(BUILTIN_SKILLS),
                "installed_count": len(installed_skills),
            },
            "plugins": {
                "configured": (self.root / ".altimate-code" / "plugins").is_dir(),
            },
            "mcp": {
                "configured": mcp_path.is_file(),
                "server_count": len(servers),
                "path": str(mcp_path),
            },
            "providers": [
                {
                    "name": item["name"],
                    "configured": bool(item["configured"]),
                    "supports_tools": bool(item["supports_tools"]),
                    "supports_streaming": bool(item["supports_streaming"]),
                    "supports_reasoning": bool(item["supports_reasoning"]),
                }
                for item in providers
            ],
        }

    def inventory(self) -> dict[str, Any]:
        project = self._hospitality_root()
        airflow, airflow_files = self._airflow_scan(project)
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
            "airflow": {"found": bool(airflow_files), **airflow.summary()},
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
        project = Path(result["hospitality_project"])
        dbt = self._dbt_discovery(project)
        airflow = self._airflow_discovery(project)
        result.update({
            "project_root": str(self.root),
            "git": self._git(),
            "dbt": dbt,
            "airflow": airflow,
            "sql": self._sql_tooling(dbt),
            "warehouses": self._warehouse_hints(),
            "agentic": self._agentic(),
        })
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


def render_discovery(result: dict[str, Any]) -> str:
    """Render secret-safe human-readable first-run discovery."""

    yes = "✓"
    no = "·"
    git = result.get("git") or {}
    dbt = result.get("dbt") or {}
    airflow = result.get("airflow") or {}
    sql = result.get("sql") or {}
    agentic = result.get("agentic") or {}
    provider_names = [
        item["name"] for item in agentic.get("providers", ())
        if item.get("configured")
    ]
    warehouse_names = [
        item["warehouse"] for item in result.get("warehouses", ())
        if item.get("configuration_detected")
    ]
    lines = ["Agentic Project Discovery", ""]
    lines += [
        f"{yes if git.get('found') else no} Git repository",
        f"  branch: {git.get('branch') or '—'}",
        f"  changed files: {len(git.get('changed_files') or ())}",
        "",
        f"{yes if dbt.get('found') else no} dbt project",
        f"  name: {dbt.get('project_name') or '—'}",
        f"  version: {dbt.get('dbt_version') or 'not installed'}",
        f"  models: {dbt.get('models', 0)}",
        f"  tests: {dbt.get('tests', 0)}",
        f"  sources: {dbt.get('sources', 0)}",
        f"  adapter: {dbt.get('adapter') or '—'}",
        "",
        f"{yes if airflow.get('found') else no} Airflow",
        f"  version: {airflow.get('version') or 'not installed'}",
        f"  DAGs: {airflow.get('dag_count', 0)}",
        f"  Assets: {airflow.get('assets_detected', 0)}",
        f"  Datasets: {airflow.get('datasets_detected', 0)}",
        "",
        f"{yes} SQL",
        f"  inferred dialect: {sql.get('dialect') or 'unknown'}",
        f"  SQLFluff: {'available' if sql.get('sqlfluff_available') else 'not installed'}",
        "",
        f"{yes if warehouse_names else no} Warehouse configuration",
        f"  detected: {', '.join(warehouse_names) if warehouse_names else 'none'}",
        "  credentials: values redacted",
        "",
        f"{yes} Agentic",
        f"  skills: {agentic.get('skills', {}).get('builtin_count', 0)} built-in",
        f"  installed project skills: {agentic.get('skills', {}).get('installed_count', 0)}",
        f"  provider: {', '.join(provider_names) if provider_names else 'not configured'}",
        f"  MCP servers: {agentic.get('mcp', {}).get('server_count', 0)}",
        "",
        "Ready.",
    ]
    return "\n".join(lines)
