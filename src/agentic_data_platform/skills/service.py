"""Executable skill catalog, persistence and deterministic orchestration."""

from __future__ import annotations

import shutil
import sqlite3
import subprocess
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, Iterable, Mapping
from urllib.parse import urlparse

import yaml

from agentic_data_platform.skills.registry import SkillRegistry, parse_skill


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
        runner: Callable[[list[str], Path | None], subprocess.CompletedProcess[str]] | None = None,
    ) -> None:
        self.project_root = Path(project_root).expanduser().resolve()
        self.global_root = Path(global_root).expanduser().resolve() if global_root else None
        self.state = SkillStateStore(state_path)
        self.runner = runner or self._default_runner

    @staticmethod
    def _default_runner(
        argv: list[str],
        cwd: Path | None = None,
    ) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            argv,
            cwd=cwd,
            capture_output=True,
            text=True,
            check=False,
        )

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

    def create(
        self,
        name: str,
        description: str,
        body: str,
        *,
        scope: str = "project",
        always_apply: bool = False,
        apply_paths: Iterable[str] = (),
    ) -> dict[str, Any]:
        if scope not in {"project", "global"}:
            raise ValueError("skill scope must be project or global")
        root = self.install_root if scope == "project" else (
            self.global_root or Path.home() / ".altimate-code" / "skills"
        )
        registry = self.registry()
        path = registry.create(
            root,
            name,
            description,
            body,
            always_apply=always_apply,
            apply_paths=apply_paths,
        )
        self.state.set_enabled(name, True)
        return {
            "status": "CREATED",
            "scope": scope,
            "name": name,
            "path": str(path),
        }

    def test(self, name: str) -> dict[str, Any]:
        skill = self.registry().get(name)
        findings = []
        if not skill.description.strip():
            findings.append("description is empty")
        if not skill.body.strip():
            findings.append("body is empty")
        if skill.path.name != "SKILL.md":
            findings.append("skill file must be named SKILL.md")
        for pattern in skill.apply_paths:
            if pattern.startswith("/"):
                findings.append(f"applyPaths must be project-relative: {pattern}")
        metadata = dict(skill.metadata or {})
        tools = metadata.get("tools") or []
        if not isinstance(tools, list):
            findings.append("tools metadata must be a list")
        return {
            "name": name,
            "status": "PASS" if not findings else "FAIL",
            "findings": findings,
            "enabled": self.state.enabled(name),
            "path": str(skill.path),
        }

    def install_source(
        self,
        source: str,
        *,
        scope: str = "project",
        name: str | None = None,
        overwrite: bool = False,
    ) -> dict[str, Any]:
        if scope not in {"project", "global"}:
            raise ValueError("skill scope must be project or global")
        destination_root = self.install_root if scope == "project" else (
            self.global_root or Path.home() / ".altimate-code" / "skills"
        )
        destination_root.mkdir(parents=True, exist_ok=True)

        source_path = Path(source).expanduser()
        temporary: tempfile.TemporaryDirectory[str] | None = None
        install_root: Path
        if source_path.exists():
            install_root = source_path.resolve()
        else:
            repo_url, separator, fragment = source.partition("#")
            parsed = urlparse(repo_url)
            if parsed.scheme != "https" or parsed.netloc.casefold() != "github.com":
                raise ValueError(
                    "remote skill installs are restricted to https://github.com URLs"
                )
            temporary = tempfile.TemporaryDirectory(prefix="ade-skill-")
            clone_root = Path(temporary.name) / "repo"
            completed = self.runner(
                ["git", "clone", "--depth", "1", repo_url, str(clone_root)],
                None,
            )
            if completed.returncode != 0:
                temporary.cleanup()
                raise RuntimeError(
                    "skill repository clone failed: "
                    + (completed.stderr or completed.stdout or "unknown git error")[-2000:]
                )
            install_root = (
                (clone_root / fragment).resolve()
                if separator and fragment
                else clone_root.resolve()
            )
            clone_resolved = clone_root.resolve()
            if (
                install_root != clone_resolved
                and clone_resolved not in install_root.parents
            ):
                temporary.cleanup()
                raise ValueError("skill subpath escapes repository root")

        try:
            candidates: list[Path] = []
            if install_root.is_file() and install_root.name == "SKILL.md":
                candidates = [install_root]
            elif install_root.is_dir():
                if (install_root / "SKILL.md").is_file():
                    candidates.append(install_root / "SKILL.md")
                for path in install_root.rglob("SKILL.md"):
                    if path in candidates or ".git" in path.parts:
                        continue
                    try:
                        relative = path.relative_to(install_root)
                    except ValueError:
                        continue
                    if len(relative.parts) <= 6:
                        candidates.append(path)

            if name:
                candidates = [
                    path for path in candidates if parse_skill(path).name == name
                ]
            if not candidates:
                raise FileNotFoundError("no matching SKILL.md found in install source")

            installed = []
            for path in candidates:
                skill = parse_skill(path)
                safe_name = skill.name.strip().replace(" ", "-")
                if not safe_name or any(
                    token in safe_name for token in ("/", "\\", "..")
                ):
                    raise ValueError(
                        f"invalid skill name in source: {skill.name!r}"
                    )
                destination = destination_root / safe_name
                if destination.exists():
                    if not overwrite:
                        raise FileExistsError(
                            f"skill already installed: {skill.name}"
                        )
                    shutil.rmtree(destination)
                destination.mkdir(parents=True)
                shutil.copy2(path, destination / "SKILL.md")
                self.state.set_enabled(skill.name, True)
                installed.append(
                    {
                        "name": skill.name,
                        "path": str(destination / "SKILL.md"),
                    }
                )
            return {
                "status": "INSTALLED",
                "scope": scope,
                "source": source,
                "installed": installed,
                "count": len(installed),
            }
        finally:
            if temporary is not None:
                temporary.cleanup()

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

    def active_registry(self) -> SkillRegistry:
        """Return only enabled skills for runtime context selection."""
        registry = self.registry()
        return SkillRegistry(
            skill for skill in registry.list() if self.state.enabled(skill.name)
        )

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
