"""Static Airflow intelligence that never imports or executes DAG modules."""

from __future__ import annotations

import ast
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any


@dataclass(frozen=True)
class AirflowDag:
    dag_id: str
    file: str
    schedule: str | None = None
    catchup: bool | None = None
    retries: int | None = None
    tasks: tuple[str, ...] = ()
    operators: tuple[str, ...] = ()
    task_groups: tuple[str, ...] = ()
    connections: tuple[str, ...] = ()
    source: str | None = None
    entities: tuple[str, ...] = ()
    writes: tuple[str, ...] = ()
    task_graph: tuple[tuple[str, str], ...] = ()
    dag_dependencies: tuple[str, ...] = ()
    dbt_commands: tuple[str, ...] = ()


@dataclass
class AirflowProject:
    dags: dict[str, AirflowDag] = field(default_factory=dict)
    parse_errors: list[dict[str, str]] = field(default_factory=list)

    @classmethod
    def scan(cls, project: str | Path) -> "AirflowProject":
        root = Path(project)
        dags_dir = root / "airflow" / "dags" if (root / "airflow" / "dags").is_dir() else root
        inventory = cls()
        template_tasks: set[str] = set()
        template_operators: set[str] = set()
        template_groups: set[str] = set()
        all_connections: set[str] = set()
        all_writes: set[str] = set()
        all_dbt_commands: set[str] = set()
        all_dag_dependencies: set[str] = set()
        relation_edges: set[tuple[str, str]] = set()
        template_schedule: str | None = None
        template_catchup: bool | None = None
        default_retries: int | None = None
        parsed: list[tuple[Path, ast.AST]] = []
        declared_aliases: list[tuple[Path, str]] = []
        for path in sorted(dags_dir.rglob("*.py")):
            try:
                tree = ast.parse(path.read_text(), filename=str(path))
                parsed.append((path, tree))
            except SyntaxError as exc:
                inventory.parse_errors.append({"file": str(path), "error": str(exc)})
                continue
            for statement in tree.body:
                if isinstance(statement, (ast.Assign, ast.AnnAssign)):
                    value = statement.value
                    literal = _literal(value)
                    targets = statement.targets if isinstance(statement, ast.Assign) else [statement.target]
                    if any(isinstance(target, ast.Name) and target.id == "_ALIASES" for target in targets) and isinstance(literal, dict):
                        declared_aliases.extend((path, str(alias)) for alias in literal if isinstance(alias, str))
                    if isinstance(literal, dict) and isinstance(literal.get("retries"), int):
                        default_retries = literal["retries"]
            for node in ast.walk(tree):
                if isinstance(node, ast.Call):
                    call_name = _call_name(node.func)
                    task_id = _keyword_text(node, "task_id")
                    if task_id:
                        template_tasks.add(task_id)
                        template_operators.add(call_name)
                    if call_name == "TaskGroup":
                        group = _keyword_literal(node, "group_id") or _positional_literal(node, 0)
                        if group:
                            template_groups.add(group)
                    for keyword in node.keywords:
                        if keyword.arg and keyword.arg.endswith("conn_id") and isinstance(keyword.value, ast.Constant):
                            all_connections.add(str(keyword.value.value))
                    command = _keyword_text(node, "bash_command")
                    if command and re.search(r"\bdbt\s+(?:build|run|test|compile|parse)\b", command):
                        all_dbt_commands.add(command)
                    trigger = _keyword_text(node, "trigger_dag_id")
                    if trigger:
                        all_dag_dependencies.add(trigger)
                    if call_name == "DAG":
                        template_schedule = _keyword_literal(node, "schedule") or template_schedule
                        catchup = _keyword_value(node, "catchup")
                        template_catchup = catchup if isinstance(catchup, bool) else template_catchup
                if isinstance(node, ast.BinOp) and isinstance(node.op, ast.RShift):
                    chain = _shift_chain(node)
                    relation_edges.update(zip(chain, chain[1:]))
                if isinstance(node, ast.Constant) and isinstance(node.value, str):
                    value = node.value.upper()
                    if "RAW." in value or "HOSPITALITY_DW.RAW" in value:
                        matches = re.findall(r"(?:HOSPITALITY_DW\.)?RAW\.([A-Z][A-Z0-9_]*)", value)
                        all_writes.update(f"HOSPITALITY_DW.RAW.{name}" for name in matches)
        for path, tree in parsed:
            for node in ast.walk(tree):
                if not isinstance(node, ast.Call):
                    continue
                call_name = _call_name(node.func)
                if call_name == "job":
                    dag_id = _positional_literal(node, 0)
                    source = _positional_literal(node, 1)
                    entities = tuple(value for value in (_literal(arg) for arg in node.args[2:]) if isinstance(value, str))
                    if dag_id:
                        inventory.dags[dag_id] = AirflowDag(
                            dag_id, str(path), schedule=template_schedule, catchup=template_catchup,
                            retries=default_retries, tasks=tuple(sorted(template_tasks)), operators=tuple(sorted(template_operators)),
                            task_groups=tuple(sorted(template_groups)), connections=tuple(sorted(all_connections)),
                            source=source, entities=entities, writes=tuple(sorted(all_writes)),
                            task_graph=tuple(sorted(relation_edges)), dag_dependencies=tuple(sorted(all_dag_dependencies)),
                            dbt_commands=tuple(sorted(all_dbt_commands)),
                        )
                elif call_name in {"DAG", "dbt_dag"}:
                    dag_id = _keyword_literal(node, "dag_id") or _positional_literal(node, 0)
                    if dag_id and "{" not in dag_id and dag_id not in inventory.dags:
                        inventory.dags[dag_id] = AirflowDag(
                            dag_id, str(path), schedule=_keyword_literal(node, "schedule"),
                            catchup=_keyword_value(node, "catchup"), retries=default_retries,
                            tasks=tuple(sorted(template_tasks)),
                            operators=tuple(sorted(template_operators)), task_groups=tuple(sorted(template_groups)),
                            connections=tuple(sorted(all_connections)), writes=tuple(sorted(all_writes)),
                            task_graph=tuple(sorted(relation_edges)), dag_dependencies=tuple(sorted(all_dag_dependencies)),
                            dbt_commands=tuple(sorted(all_dbt_commands)),
                        )
        # Alias DAGs generated by a factory may not contain a literal ``DAG``
        # call with the alias name. Register their declared names so static
        # inventory matches the runtime DagBag without importing user code.
        for path, dag_id in declared_aliases:
            inventory.dags.setdefault(
                dag_id,
                AirflowDag(
                    dag_id, str(path), schedule=template_schedule, catchup=template_catchup,
                    retries=default_retries, tasks=tuple(sorted(template_tasks)),
                    operators=tuple(sorted(template_operators)), task_groups=tuple(sorted(template_groups)),
                    connections=tuple(sorted(all_connections)), writes=tuple(sorted(all_writes)),
                    task_graph=tuple(sorted(relation_edges)), dag_dependencies=tuple(sorted(all_dag_dependencies)),
                    dbt_commands=tuple(sorted(all_dbt_commands)),
                ),
            )
        return inventory

    def summary(self) -> dict[str, Any]:
        return {
            "dag_count": len(self.dags),
            "parse_errors": self.parse_errors,
            "connections_used": sorted({item for dag in self.dags.values() for item in dag.connections}),
            "dags": sorted(self.dags),
        }

    def details(self, dag_id: str) -> dict[str, Any]:
        from dataclasses import asdict

        try:
            return asdict(self.dags[dag_id])
        except KeyError as exc:
            raise KeyError(f"Airflow DAG not found: {dag_id}") from exc

    def find_writing(self, target: str) -> list[str]:
        target_upper = target.upper()
        return sorted(dag.dag_id for dag in self.dags.values() if any(target_upper in item.upper() for item in dag.writes))

    def task_graph(self, dag_id: str) -> dict[str, Any]:
        dag = self.dags.get(dag_id)
        if dag is None:
            raise KeyError(f"Airflow DAG not found: {dag_id}")
        return {"dag_id": dag_id, "tasks": list(dag.tasks), "edges": [list(edge) for edge in dag.task_graph]}

    def dependencies(self, dag_id: str) -> dict[str, Any]:
        dag = self.dags.get(dag_id)
        if dag is None:
            raise KeyError(f"Airflow DAG not found: {dag_id}")
        depended_on_by = sorted(item.dag_id for item in self.dags.values() if dag_id in item.dag_dependencies)
        return {"dag_id": dag_id, "triggers": list(dag.dag_dependencies), "triggered_by": depended_on_by}

    def connections_used(self, dag_id: str | None = None) -> list[str]:
        dags = [self.dags[dag_id]] if dag_id else list(self.dags.values())
        return sorted({connection for dag in dags for connection in dag.connections})

    def health(self) -> dict[str, Any]:
        return {
            "status": "PASS" if self.dags and not self.parse_errors else "FAIL",
            "dag_count": len(self.dags), "parse_error_count": len(self.parse_errors),
            "parse_errors": self.parse_errors, "mode": "STATIC",
        }

    def failure_summary(self) -> dict[str, Any]:
        return {
            "mode": "STATIC", "live_state": "SKIPPED - Airflow API/database not configured",
            "parse_failures": self.parse_errors,
        }


def _call_name(node: ast.AST) -> str:
    if isinstance(node, ast.Name):
        return node.id
    if isinstance(node, ast.Attribute):
        return node.attr
    return "unknown"


def _literal(node: ast.AST) -> Any:
    try:
        return ast.literal_eval(node)
    except (ValueError, TypeError):
        return None


def _positional_literal(node: ast.Call, position: int) -> Any:
    return _literal(node.args[position]) if len(node.args) > position else None


def _keyword_value(node: ast.Call, name: str) -> Any:
    for keyword in node.keywords:
        if keyword.arg == name:
            return _literal(keyword.value)
    return None


def _keyword_literal(node: ast.Call, name: str) -> str | None:
    value = _keyword_value(node, name)
    return str(value) if isinstance(value, (str, int, float)) else None


def _text(node: ast.AST) -> str | None:
    value = _literal(node)
    if isinstance(value, (str, int, float)):
        return str(value)
    if isinstance(node, ast.JoinedStr):
        parts: list[str] = []
        for part in node.values:
            if isinstance(part, ast.Constant):
                parts.append(str(part.value))
            elif isinstance(part, ast.FormattedValue):
                parts.append("{" + ast.unparse(part.value) + "}")
        return "".join(parts)
    return None


def _keyword_text(node: ast.Call, name: str) -> str | None:
    for keyword in node.keywords:
        if keyword.arg == name:
            return _text(keyword.value)
    return None


def _relation_name(node: ast.AST) -> str | None:
    if isinstance(node, ast.Name):
        return node.id
    if isinstance(node, ast.Attribute):
        return ast.unparse(node)
    return None


def _shift_chain(node: ast.AST) -> list[str]:
    if isinstance(node, ast.BinOp) and isinstance(node.op, ast.RShift):
        return _shift_chain(node.left) + _shift_chain(node.right)
    name = _relation_name(node)
    return [name] if name else []
