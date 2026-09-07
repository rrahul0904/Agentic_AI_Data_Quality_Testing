"""Named learned-training lifecycle compatible with Altimate teammate training."""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any

from agentic_data_platform.memory import MemoryStore


TRAINING_MAX_PER_KIND = 50
TRAINING_BUDGET = 48000


def slugify(text: str) -> str:
    value = text.casefold()
    value = re.sub(r"[^a-z0-9\s_-]", "", value)
    value = re.sub(r"\s+", "-", value)
    value = value.strip("-_")[:64]
    return value or "untitled"


def parse_markdown_sections(markdown: str) -> list[dict[str, str]]:
    sections: list[dict[str, str]] = []
    current_h1 = ""
    current_name = ""
    current_content: list[str] = []

    def flush() -> None:
        nonlocal current_name, current_content
        if current_name and any(line.strip() for line in current_content):
            sections.append(
                {
                    "name": slugify(current_name),
                    "content": "\n".join(current_content).strip(),
                }
            )

    for line in markdown.splitlines():
        if re.match(r"^#\s+", line):
            flush()
            current_h1 = re.sub(r"^#\s+", "", line).strip()
            current_name = ""
            current_content = []
            continue
        if re.match(r"^##\s+", line):
            flush()
            current_name = re.sub(r"^##\s+", "", line).strip()
            current_content = (
                [f"Context: {current_h1}", ""]
                if current_h1
                else []
            )
            continue
        if current_name:
            current_content.append(line)

    flush()
    return sections


def save_entry(
    store: MemoryStore,
    *,
    kind: str,
    name: str,
    content: str,
    scope: str = "project",
    project_id: str | None = None,
    source: str | None = None,
    citations: list[str] | None = None,
) -> dict[str, Any]:
    result = store.save_named_training(
        kind,
        name,
        content,
        scope=scope,
        project_id=project_id,
        source=source,
        citations=citations,
        max_per_kind=TRAINING_MAX_PER_KIND,
    )
    return {
        "status": "PASS",
        **result,
        "budget": store.named_training_budget(
            scope=None,
            project_id=project_id,
            budget=TRAINING_BUDGET,
        ),
    }


def list_entries(
    store: MemoryStore,
    *,
    kind: str | None = None,
    scope: str = "all",
    project_id: str | None = None,
) -> dict[str, Any]:
    scope_filter = None if scope == "all" else scope
    entries = store.list_named_training(
        scope=scope_filter,
        project_id=project_id,
        kind=kind,
    )
    return {
        "status": "PASS",
        "entries": entries,
        "count": len(entries),
        "counts": store.named_training_counts(
            scope=scope_filter,
            project_id=project_id,
        ),
        "budget": store.named_training_budget(
            scope=scope_filter,
            project_id=project_id,
            budget=TRAINING_BUDGET,
        ),
    }


def remove_entry(
    store: MemoryStore,
    *,
    kind: str,
    name: str,
    scope: str = "project",
    project_id: str | None = None,
) -> dict[str, Any]:
    result = store.remove_named_training(
        scope,
        kind,
        name,
        project_id=project_id,
    )
    return {
        "status": "PASS",
        **result,
        "budget": store.named_training_budget(
            project_id=project_id,
            budget=TRAINING_BUDGET,
        ),
    }


def import_markdown(
    store: MemoryStore,
    file_path: str | Path,
    *,
    kind: str,
    scope: str = "project",
    project_id: str | None = None,
    dry_run: bool = True,
    max_entries: int = 20,
) -> dict[str, Any]:
    path = Path(file_path).expanduser().resolve()
    markdown = path.read_text(errors="replace")
    sections = parse_markdown_sections(markdown)
    if not sections:
        return {
            "status": "FAIL",
            "reason": "NO_SECTIONS",
            "file_path": str(path),
            "count": 0,
            "sections": [],
        }

    current = store.named_training_counts(
        scope=scope,
        project_id=project_id,
    ).get(kind, 0)
    available = max(0, TRAINING_MAX_PER_KIND - current)
    bounded = sections[: max(0, min(int(max_entries), len(sections)))]
    preview = []
    for index, section in enumerate(bounded):
        preview.append(
            {
                "name": section["name"],
                "content": section["content"][:1800],
                "will_import": index < available,
            }
        )

    if dry_run:
        return {
            "status": "PASS",
            "dry_run": True,
            "file_path": str(path),
            "kind": kind,
            "scope": scope,
            "sections_found": len(sections),
            "current_count": current,
            "capacity": TRAINING_MAX_PER_KIND,
            "available": available,
            "count": min(len(preview), available),
            "sections": preview,
        }

    imported = []
    skipped = []
    for index, section in enumerate(bounded):
        if index >= available:
            skipped.append(
                {"name": section["name"], "reason": "capacity"}
            )
            continue
        try:
            imported.append(
                store.save_named_training(
                    kind,
                    section["name"],
                    section["content"][:1800],
                    scope=scope,
                    project_id=project_id,
                    source=str(path),
                    max_per_kind=TRAINING_MAX_PER_KIND,
                )
            )
        except Exception as exc:
            skipped.append(
                {
                    "name": section["name"],
                    "reason": f"{type(exc).__name__}: {exc}",
                }
            )

    return {
        "status": "PASS",
        "dry_run": False,
        "file_path": str(path),
        "kind": kind,
        "scope": scope,
        "sections_found": len(sections),
        "imported": imported,
        "skipped": skipped,
        "count": len(imported),
        "budget": store.named_training_budget(
            project_id=project_id,
            budget=TRAINING_BUDGET,
        ),
    }
