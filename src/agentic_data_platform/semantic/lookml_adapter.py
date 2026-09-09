"""Lightweight LookML adapter for the ADE semantic registry."""

from __future__ import annotations

from pathlib import Path
import re
from typing import Any

from agentic_data_platform.semantic.registry import SemanticElement, SemanticRegistry


_IGNORED = {".git", "target", "node_modules", ".venv", "venv"}


def _lookml_files(root: Path) -> list[Path]:
    files: list[Path] = []
    for path in root.rglob("*.lkml"):
        if not path.is_file():
            continue
        if any(part in _IGNORED for part in path.relative_to(root).parts):
            continue
        files.append(path)
    return sorted(files)


def _named_blocks(text: str, keyword: str) -> list[tuple[str, str]]:
    pattern = re.compile(r"(?m)^\s*" + re.escape(keyword) + r":\s*([A-Za-z_][A-Za-z0-9_]*)\s*\{")
    blocks: list[tuple[str, str]] = []
    for match in pattern.finditer(text):
        depth = 1
        index = match.end()
        start = index
        in_quote = False
        while index < len(text) and depth:
            char = text[index]
            if char == "\"" and (index == 0 or text[index - 1] != "\\\\"):
                in_quote = not in_quote
                index += 1
                continue
            if not in_quote and text.startswith("${", index):
                close = text.find("}", index + 2)
                if close < 0:
                    index = len(text)
                    break
                index = close + 1
                continue
            if not in_quote:
                if char == "{":
                    depth += 1
                elif char == "}":
                    depth -= 1
                    if depth == 0:
                        blocks.append((match.group(1), text[start:index]))
                        break
            index += 1
    return blocks


def _value(body: str, key: str) -> str | None:
    sql_pattern = re.compile(r"(?ms)^\s*" + re.escape(key) + r":\s*(.*?)\s*;;")
    sql_match = sql_pattern.search(body)
    if sql_match:
        return sql_match.group(1).strip()
    plain = re.compile(r"(?m)^\s*" + re.escape(key) + r":\s*(?:\"([^\"]*)\"|([^\s#]+))")
    match = plain.search(body)
    if not match:
        return None
    return (match.group(1) or match.group(2) or "").strip()


def ingest_lookml_project(
    registry: SemanticRegistry,
    project_root: str | Path,
    *,
    resource_name: str | None = None,
) -> dict[str, Any]:
    """Ingest LookML views, fields, explores and joins without a Looker runtime."""
    root = Path(project_root).expanduser().resolve()
    if not root.is_dir():
        raise FileNotFoundError(root)

    name = resource_name or root.name
    elements: list[SemanticElement] = []
    relationships: list[dict[str, Any]] = []
    parsed_files: list[str] = []

    for path in _lookml_files(root):
        relative = str(path.relative_to(root))
        text = path.read_text()
        found = False

        for view_name, body in _named_blocks(text, "view"):
            found = True
            elements.append(
                SemanticElement(
                    "view",
                    view_name,
                    expression=_value(body, "sql_table_name"),
                    metadata={"source": relative},
                )
            )
            for keyword, kind in (
                ("dimension", "dimension"),
                ("dimension_group", "dimension_group"),
                ("measure", "measure"),
                ("filter", "filter"),
                ("parameter", "parameter"),
            ):
                for field_name, field_body in _named_blocks(body, keyword):
                    elements.append(
                        SemanticElement(
                            kind,
                            field_name,
                            parent=view_name,
                            description=str(_value(field_body, "description") or ""),
                            expression=_value(field_body, "sql"),
                            data_type=_value(field_body, "type"),
                            metadata={
                                "source": relative,
                                "primary_key": _value(field_body, "primary_key") == "yes",
                                "hidden": _value(field_body, "hidden") == "yes",
                            },
                        )
                    )

        for explore_name, body in _named_blocks(text, "explore"):
            found = True
            elements.append(
                SemanticElement(
                    "explore",
                    explore_name,
                    metadata={"source": relative, "from": _value(body, "from")},
                )
            )
            for join_name, join_body in _named_blocks(body, "join"):
                right = _value(join_body, "from") or join_name
                relationships.append(
                    {
                        "name": f"{explore_name}.{join_name}",
                        "left_table": explore_name,
                        "right_table": right,
                        "type": _value(join_body, "type") or "left_outer",
                        "relationship": _value(join_body, "relationship") or "many_to_one",
                        "sql_on": _value(join_body, "sql_on"),
                        "foreign_key": _value(join_body, "foreign_key"),
                        "source": relative,
                    }
                )

        if found:
            parsed_files.append(relative)

    resource_id = registry.upsert_resource(
        name=name,
        provider="lookml",
        description=f"LookML project: {name}",
        metadata={
            "project_root": str(root),
            "files": sorted(set(parsed_files)),
            "view_count": sum(item.kind == "view" for item in elements),
            "explore_count": sum(item.kind == "explore" for item in elements),
        },
    )
    registry.replace_contents(
        resource_id,
        elements=elements,
        relationships=relationships,
        verified_queries=[],
    )
    return registry.show(resource_id)
