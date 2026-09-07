"""Process-safe-shaped adapter around the standalone ShiftForge Python package.

The adapter deliberately returns plain JSON-compatible dictionaries so callers do
not depend on ShiftForge's Pydantic models or human CLI output.
"""

from __future__ import annotations

import importlib
import sys
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Iterator


@contextmanager
def _shiftforge_imports(root: str | Path) -> Iterator[None]:
    path = Path(root).expanduser().resolve()
    source = path / "src"
    if not source.is_dir():
        raise FileNotFoundError(f"ShiftForge source directory not found: {source}")
    sys.path.insert(0, str(source))
    try:
        yield
    finally:
        try:
            sys.path.remove(str(source))
        except ValueError:
            pass


def _model_dump(value: Any) -> dict[str, Any]:
    if hasattr(value, "model_dump"):
        return value.model_dump(mode="json")
    if hasattr(value, "dict"):
        return value.dict()
    return dict(value)


class ShiftForgeAdapter:
    def __init__(self, root: str | Path) -> None:
        self.root = Path(root).expanduser().resolve()

    def _engine(self):
        with _shiftforge_imports(self.root):
            return importlib.import_module("shiftforge.engine").ConversionEngine()

    def scan(self, project: str | Path) -> dict[str, Any]:
        with _shiftforge_imports(self.root):
            discover = importlib.import_module("shiftforge.dbt").discover_models
            root = Path(project).expanduser().resolve()
            models = discover(root)
            return {"project": str(root), "models": len(models), "model_paths": [str(path.relative_to(root)) for path in models]}

    def inventory(self, project: str | Path) -> dict[str, Any]:
        root = Path(project).expanduser().resolve()
        scanned = self.scan(root)
        manifest = root / "target" / "manifest.json"
        manifest_value: dict[str, Any] = {}
        if manifest.is_file():
            import json

            payload = json.loads(manifest.read_text(encoding="utf-8"))
            resources = [*payload.get("nodes", {}).values(), *payload.get("sources", {}).values()]
            manifest_value = {
                "manifest": str(manifest),
                "models": sum(item.get("resource_type") == "model" for item in resources),
                "sources": sum(item.get("resource_type") == "source" for item in resources),
                "tests": sum(item.get("resource_type") == "test" for item in resources),
                "snapshots": sum(item.get("resource_type") == "snapshot" for item in resources),
                "incremental_models": sum(item.get("config", {}).get("materialized") == "incremental" for item in resources),
            }
        return {"source_dialect": "bigquery", "target_dialect": "redshift", **scanned, **manifest_value}

    def convert_model(self, sql: str, model_name: str = "model.sql", hints: dict[str, str] | None = None) -> dict[str, Any]:
        return _model_dump(self._engine().convert_sql(sql, model_name=model_name, hints=hints or {}))

    def convert_project(self, project: str | Path, *, hints: dict[str, dict[str, str]] | None = None) -> dict[str, Any]:
        report = self._engine().convert_project(Path(project), hints=hints or {}, write=False)
        return _model_dump(report)

    def validate(self, project: str | Path, converted: str | Path) -> dict[str, Any]:
        with _shiftforge_imports(self.root):
            result = importlib.import_module("shiftforge.validator").compile_isolated(Path(project), Path(converted))
            return _model_dump(result) if hasattr(result, "model_dump") else {
                "ok": result.ok, "exit_code": result.exit_code, "stdout": result.stdout, "stderr": result.stderr,
            }

    def findings(self, project: str | Path) -> dict[str, Any]:
        report = self.convert_project(project)
        findings = []
        for result in report.get("results", []):
            findings.extend({"model": result.get("model"), **hit} for hit in result.get("hits", []))
        return {"project": str(Path(project).resolve()), "findings": findings, "count": len(findings)}

    def blockers(self, project: str | Path) -> dict[str, Any]:
        report = self.convert_project(project)
        blockers = []
        for result in report.get("results", []):
            if result.get("status") == "blocked" or result.get("unresolved"):
                blockers.append({"model": result.get("model"), "status": result.get("status"), "unresolved": result.get("unresolved", [])})
        return {"project": str(Path(project).resolve()), "blockers": blockers, "count": len(blockers)}
