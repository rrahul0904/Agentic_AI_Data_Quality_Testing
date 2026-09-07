"""Executable skill catalog, persistence and deterministic orchestration."""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, Iterable, Mapping

import yaml

from agentic_data_platform.skills.registry import SkillRegistry


@dataclass(frozen=True)
class BuiltinSkill:
    name: str
    description: str
    tools: tuple[str, ...]
    body: str
    always_apply: bool = False


def _body(name: str, tools: tuple[str, ...], purpose: str) -> str:
    return (
        f"# {name}\n\n"
        f"{purpose}\n\n"
        "Use deterministic tools in this order:\n"
        + "\n".join(f"{index}. {tool}" for index, tool in enumerate(tools, 1))
        + "\n\nNever claim success from narrative alone; report tool evidence and explicit SKIP_EXTERNAL states."
    )


_BUILTIN_DEFS: tuple[tuple[str, str, tuple[str, ...]], ...] = (
    ("altimate-setup", "Inspect platform readiness and configured integrations.", ("doctor", "platform_discover", "connection_discover", "mcp_discover")),
    ("cost-report", "Build query and warehouse cost evidence.", ("finops_report",)),
    ("data-parity", "Compare source and target data with scalable cascade diff.", ("data_diff_plan", "data_diff_cascade")),
    ("data-viz", "Prepare bounded query results and visualization-ready evidence.", ("sql_execute",)),
    ("dbt-analyze", "Analyze dbt artifacts, coverage, lineage, compiled SQL and validators.", ("dbt_manifest_summary", "dbt_test_coverage", "dbt_compiled_sql_review", "dbt_validate")),
    ("dbt-develop", "Develop and verify dbt changes through governed compile/build.", ("dbt_compile", "dbt_build", "dbt_validate")),
    ("dbt-docs", "Find and resolve dbt documentation gaps.", ("dbt_documentation_gaps",)),
    ("dbt-pr-review", "Review dbt changes with impact, validators and recommended tests.", ("dbt_validate", "column_lineage_diff", "change_impact", "recommended_tests")),
    ("dbt-schema-verify", "Verify declared dbt columns against built catalog schema.", ("dbt_validate",)),
    ("dbt-test", "Generate and execute dbt schema tests.", ("dbt_test_generate", "dbt_test")),
    ("dbt-troubleshoot", "Diagnose failed dbt nodes and test failures.", ("dbt_failed_models", "dbt_failed_tests", "dbt_validate")),
    ("dbt-unit-tests", "Generate dbt 1.8+ unit tests from compiled SQL and lineage.", ("dbt_unit_test_gen",)),
    ("lineage-diff", "Compare project column lineage across artifact states.", ("column_lineage_diff",)),
    ("pii-audit", "Classify, propagate and audit access to sensitive data.", ("pii_scan", "pii_lineage", "pii_access_report")),
    ("query-optimize", "Review, explain and optimize SQL with warehouse evidence.", ("sql_review", "sql_explain", "sql_optimize")),
    ("schema-migration", "Plan, convert and validate warehouse schema/model migrations.", ("migration_plan", "migration_convert_project", "migration_validate")),
    ("sql-review", "Review SQL for correctness, safety, lineage and PII policy.", ("sql_review", "sql_column_lineage", "pii_policy_check")),
    ("sql-translate", "Translate SQL and review semantic risk.", ("sql_translate", "sql_review")),
    ("teach", "Explain platform behavior using training and deterministic evidence.", ("training_search",)),
    ("train", "Ingest approved project knowledge into the local training store.", ("training_ingest",)),
    ("training-status", "Report training corpus and indexing status.", ("training_status",)),
)


BUILTIN_SKILLS = {
    name: BuiltinSkill(name, description, tools, _body(name, tools, description))
    for name, description, tools in _BUILTIN_DEFS
}


class SkillStateStore:
    def __init__(self, path: str | Path = ":memory:") -> None:
        self.path = str(path)
        if self.path != ":memory:":
            Path(self.path).parent.mkdir(parents=True, exist_ok=True)
        self.connection = sqlite3.connect(self.path)
        self.connection.row_factory = sqlite3.Row
        self.connection.execute(
            """
            CREATE TABLE IF NOT EXISTS skill_state (
              name TEXT PRIMARY KEY,
              enabled INTEGER NOT NULL DEFAULT 1
            )
            """
        )
        self.connection.commit()

    def set_enabled(self, name: str, enabled: bool) -> None:
        self.connection.execute(
            """
            INSERT INTO skill_state(name, enabled) VALUES (?, ?)
            ON CONFLICT(name) DO UPDATE SET enabled=excluded.enabled
            """,
            (name, int(enabled)),
        )
        self.connection.commit()

    def enabled(self, name: str) -> bool:
        row = self.connection.execute(
            "SELECT enabled FROM skill_state WHERE name = ?",
            (name,),
        ).fetchone()
        return True if row is None else bool(row["enabled"])

    def status(self) -> dict[str, bool]:
        return {
            str(row["name"]): bool(row["enabled"])
            for row in self.connection.execute(
                "SELECT name, enabled FROM skill_state ORDER BY name"
            ).fetchall()
        }


class SkillService:
    def __init__(
        self,
        project_root: str | Path,
        *,
        state_path: str | Path = ":memory:",
        global_root: str | Path | None = None,
    ) -> None:
        self.project_root = Path(project_root).expanduser().resolve()
        self.global_root = Path(global_root).expanduser().resolve() if global_root else None
        self.state = SkillStateStore(state_path)

    @property
    def install_root(self) -> Path:
        return self.project_root / ".altimate-code" / "skills"

    def catalog(self) -> list[dict[str, Any]]:
        return [
            {
                "name": item.name,
                "description": item.description,
                "tools": list(item.tools),
                "always_apply": item.always_apply,
            }
            for item in sorted(BUILTIN_SKILLS.values(), key=lambda item: item.name)
        ]

    def install(self, name: str, *, overwrite: bool = False) -> dict[str, Any]:
        try:
            builtin = BUILTIN_SKILLS[name]
        except KeyError as exc:
            raise KeyError(f"builtin skill not found: {name}") from exc
        folder = self.install_root / name
        path = folder / "SKILL.md"
        if path.exists() and not overwrite:
            raise FileExistsError(f"skill already installed: {name}")
        folder.mkdir(parents=True, exist_ok=True)
        metadata = {
            "name": builtin.name,
            "description": builtin.description,
            "alwaysApply": builtin.always_apply,
            "tools": list(builtin.tools),
            "builtin": True,
        }
        path.write_text(
            "---\n"
            + yaml.safe_dump(metadata, sort_keys=False).strip()
            + "\n---\n\n"
            + builtin.body
            + "\n"
        )
        self.state.set_enabled(name, True)
        return self.inspect(name)

    def install_all(self, *, overwrite: bool = False) -> dict[str, Any]:
        installed = []
        skipped = []
        for name in sorted(BUILTIN_SKILLS):
            try:
                installed.append(self.install(name, overwrite=overwrite)["name"])
            except FileExistsError:
                skipped.append(name)
        return {"installed": installed, "skipped": skipped, "count": len(installed)}

    def registry(self) -> SkillRegistry:
        return SkillRegistry.discover(
            self.project_root,
            global_root=self.global_root,
        )

    def list(self) -> list[dict[str, Any]]:
        items = []
        for skill in self.registry().list():
            metadata = dict(skill.metadata or {})
            items.append(
                {
                    "name": skill.name,
                    "description": skill.description,
                    "path": str(skill.path),
                    "enabled": self.state.enabled(skill.name),
                    "always_apply": skill.always_apply,
                    "apply_paths": list(skill.apply_paths),
                    "tools": list(metadata.get("tools") or ()),
                    "builtin": bool(metadata.get("builtin")),
                }
            )
        return items

    def inspect(self, name: str) -> dict[str, Any]:
        skill = self.registry().get(name)
        metadata = dict(skill.metadata or {})
        return {
            "name": skill.name,
            "description": skill.description,
            "body": skill.body,
            "path": str(skill.path),
            "enabled": self.state.enabled(name),
            "always_apply": skill.always_apply,
            "apply_paths": list(skill.apply_paths),
            "tools": list(metadata.get("tools") or ()),
            "builtin": bool(metadata.get("builtin")),
        }

    def set_enabled(self, name: str, enabled: bool) -> dict[str, Any]:
        self.registry().get(name)
        self.state.set_enabled(name, enabled)
        return self.inspect(name)

    def remove(self, name: str) -> dict[str, Any]:
        skill = self.registry().get(name)
        path = skill.path
        path.unlink(missing_ok=True)
        try:
            path.parent.rmdir()
        except OSError:
            pass
        return {"name": name, "removed": True}

    def auto_load(self) -> list[dict[str, Any]]:
        return [
            self.inspect(skill.name)
            for skill in self.registry().auto_load(self.project_root)
            if self.state.enabled(skill.name)
        ]

    def plan(self, name: str, available_tools: Iterable[str]) -> dict[str, Any]:
        skill = self.inspect(name)
        if not skill["enabled"]:
            return {"name": name, "status": "DISABLED", "steps": []}
        available = set(available_tools)
        missing = [tool for tool in skill["tools"] if tool not in available]
        return {
            "name": name,
            "status": "READY" if not missing else "BLOCKED",
            "steps": [{"index": i + 1, "tool": tool} for i, tool in enumerate(skill["tools"])],
            "missing_tools": missing,
        }

    def execute(
        self,
        name: str,
        *,
        available_tools: Iterable[str],
        invoke: Callable[[str, dict[str, Any]], dict[str, Any]],
        args: Mapping[str, Any] | None = None,
        tool_args: Mapping[str, Mapping[str, Any]] | None = None,
    ) -> dict[str, Any]:
        plan = self.plan(name, available_tools)
        if plan["status"] != "READY":
            return {**plan, "results": []}
        results = []
        common = dict(args or {})
        per_tool = tool_args or {}
        for step in plan["steps"]:
            tool = step["tool"]
            payload = {**common, **dict(per_tool.get(tool, {}))}
            try:
                result = invoke(tool, payload)
            except Exception as exc:
                results.append(
                    {
                        "tool": tool,
                        "status": "ERROR",
                        "error": f"{type(exc).__name__}: {exc}",
                    }
                )
                return {
                    **plan,
                    "status": "FAIL",
                    "results": results,
                    "completed_steps": len(results) - 1,
                }
            results.append(
                {
                    "tool": tool,
                    "status": result.get("status", "PASS"),
                    "result": result,
                }
            )
            if str(result.get("status") or "").upper() in {"FAIL", "BLOCK", "ERROR"}:
                return {
                    **plan,
                    "status": "FAIL",
                    "results": results,
                    "completed_steps": len(results),
                }
        return {
            **plan,
            "status": "PASS",
            "results": results,
            "completed_steps": len(results),
        }
