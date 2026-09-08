"""Structured observable-behavior conformance for Altimate-class capabilities."""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, Iterable, Mapping

import yaml

from agentic_data_platform.models import ActorMode, Environment, ToolRequest
from agentic_data_platform.tools.builtin import build_tool_registry
from agentic_data_platform.tools.registry import ToolInvocation, ToolRegistry


@dataclass(frozen=True)
class ConformanceCase:
    case_id: str
    capability: str
    tool: str
    args: dict[str, Any]
    expected_properties: tuple[dict[str, Any], ...]
    severity: str = "major"
    reference: str = "fixture"


def load_cases(root: str | Path) -> list[ConformanceCase]:
    cases: list[ConformanceCase] = []
    for path in sorted(Path(root).rglob("*.y*ml")):
        raw = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
        for item in raw if isinstance(raw, list) else [raw]:
            cases.append(
                ConformanceCase(
                    case_id=str(item["id"]),
                    capability=str(item["capability"]),
                    tool=str(item.get("tool") or item["capability"]),
                    args=dict(item.get("input") or {}),
                    expected_properties=tuple(dict(value) for value in item.get("expected_properties") or ()),
                    severity=str(item.get("severity") or "major"),
                    reference=str(item.get("reference") or path.as_posix()),
                )
            )
    return cases


def _expand(value: Any, project: Path) -> Any:
    if isinstance(value, str):
        return value.replace("$PROJECT", str(project))
    if isinstance(value, list):
        return [_expand(item, project) for item in value]
    if isinstance(value, dict):
        return {key: _expand(item, project) for key, item in value.items()}
    return value


def _value_at(value: Any, dotted: str) -> Any:
    current = value
    for token in dotted.split("."):
        if isinstance(current, Mapping):
            current = current[token]
        elif isinstance(current, (list, tuple)) and token.isdigit():
            current = current[int(token)]
        else:
            raise KeyError(dotted)
    return current


def compare_property(actual: Any, expected: dict[str, Any]) -> tuple[bool, str]:
    dotted = str(expected["path"])
    try:
        value = _value_at(actual, dotted)
    except (KeyError, IndexError):
        return False, f"{dotted}: missing"
    if "equals" in expected:
        wanted = expected["equals"]
        return value == wanted, f"{dotted}: expected {wanted!r}, got {value!r}"
    if "one_of" in expected:
        wanted = list(expected["one_of"])
        return value in wanted, f"{dotted}: expected one of {wanted!r}, got {value!r}"
    if "contains" in expected:
        wanted = expected["contains"]
        try:
            matched = wanted in value
        except TypeError:
            matched = False
        return matched, f"{dotted}: expected to contain {wanted!r}"
    if "length_at_least" in expected:
        wanted = int(expected["length_at_least"])
        try:
            length = len(value)
        except TypeError:
            return False, f"{dotted}: value has no length"
        return length >= wanted, f"{dotted}: expected length >= {wanted}, got {length}"
    if expected.get("truthy") is True:
        return bool(value), f"{dotted}: expected a truthy value"
    if expected.get("falsey") is True:
        return not bool(value), f"{dotted}: expected a falsey value"
    raise ValueError(f"unsupported comparator for {dotted}")


class ConformanceRunner:
    def __init__(
        self,
        project_root: str | Path,
        *,
        registry: ToolRegistry | None = None,
        invoke: Callable[[str, dict[str, Any]], dict[str, Any]] | None = None,
    ) -> None:
        self.project_root = Path(project_root).expanduser().resolve()
        self.registry = registry or build_tool_registry()
        self.custom_invoke = invoke

    def invoke(self, tool: str, args: dict[str, Any]) -> dict[str, Any]:
        if self.custom_invoke is not None:
            return self.custom_invoke(tool, args)
        definition = self.registry.describe(tool)
        return self.registry.invoke(
            ToolInvocation(
                ToolRequest(
                    tool=tool,
                    operation=tool,
                    environment=Environment.DEV,
                    risk=definition.risk,
                    args=args,
                ),
                run_id=f"conformance-{tool}",
                actor_mode=ActorMode.ANALYST,
            )
        )

    def run_case(self, case: ConformanceCase) -> dict[str, Any]:
        args = _expand(case.args, self.project_root)
        if not any(key in args for key in ("project", "project_path", "target_dir", "dbt_project")):
            args["project"] = str(self.project_root)
        try:
            actual = self.invoke(case.tool, args)
        except KeyError as exc:
            return {
                "id": case.case_id,
                "capability": case.capability,
                "tool": case.tool,
                "status": "UNSUPPORTED",
                "severity": case.severity,
                "difference": str(exc),
                "reference": case.reference,
            }
        except Exception as exc:
            return {
                "id": case.case_id,
                "capability": case.capability,
                "tool": case.tool,
                "status": "DIVERGENCE",
                "severity": case.severity,
                "difference": f"{type(exc).__name__}: {exc}",
                "reference": case.reference,
            }

        differences = []
        for expected in case.expected_properties:
            matched, detail = compare_property(actual, expected)
            if not matched:
                differences.append({"property": expected, "detail": detail})
        return {
            "id": case.case_id,
            "capability": case.capability,
            "tool": case.tool,
            "status": "MATCH" if not differences else "DIVERGENCE",
            "severity": case.severity,
            "reference": case.reference,
            "agentic_result": actual,
            "reference_expectation": list(case.expected_properties),
            "differences": differences,
            "recommended_action": None if not differences else f"Review {case.tool} against {case.case_id}",
        }

    def run(self, cases: Iterable[ConformanceCase]) -> dict[str, Any]:
        results = [self.run_case(case) for case in cases]
        capabilities: dict[str, dict[str, int]] = {}
        for result in results:
            bucket = capabilities.setdefault(
                result["capability"],
                {"cases": 0, "match": 0, "divergence": 0, "unsupported": 0},
            )
            bucket["cases"] += 1
            bucket[result["status"].casefold()] += 1
        counts = {
            "cases": len(results),
            "match": sum(item["status"] == "MATCH" for item in results),
            "divergence": sum(item["status"] == "DIVERGENCE" for item in results),
            "unsupported": sum(item["status"] == "UNSUPPORTED" for item in results),
        }
        return {
            "status": "PASS" if counts["divergence"] == 0 else "FAIL",
            "counts": counts,
            "capabilities": capabilities,
            "results": results,
        }


def write_report(report: dict[str, Any], output_dir: str | Path) -> tuple[Path, Path]:
    root = Path(output_dir)
    root.mkdir(parents=True, exist_ok=True)
    json_path = root / "conformance-report.json"
    markdown_path = root / "conformance-report.md"
    json_path.write_text(json.dumps(report, indent=2, default=str) + "\n", encoding="utf-8")
    lines = [
        "# Behavioral Conformance Report",
        "",
        "| Capability | Cases | Match | Divergence | Unsupported |",
        "|---|---:|---:|---:|---:|",
    ]
    for name, counts in sorted(report["capabilities"].items()):
        lines.append(
            f"| {name} | {counts['cases']} | {counts['match']} | {counts['divergence']} | {counts['unsupported']} |"
        )
    for item in report["results"]:
        if item["status"] != "MATCH":
            lines.extend(
                [
                    "",
                    f"## {item['id']} · {item['status']}",
                    f"- tool: {item['tool']}",
                    f"- severity: {item['severity']}",
                    f"- difference: {item.get('difference') or item.get('differences')}",
                ]
            )
    markdown_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return json_path, markdown_path
