"""Deterministic project/global instruction and rule hierarchy."""

from __future__ import annotations

import fnmatch
import hashlib
import json
import os
from pathlib import Path
import re
from typing import Any, Iterable

from agentic_data_platform.models import utc_now


_STATIC_INSTRUCTIONS = (
    ("AGENTS.md", 40),
    ("CLAUDE.md", 30),
    (".github/copilot-instructions.md", 20),
    (".altimate-code/instructions.md", 10),
)
_NAME = re.compile(r"^[A-Za-z0-9_.-]{1,80}$")


def _digest(value: Any) -> str:
    return hashlib.sha256(
        json.dumps(value, sort_keys=True, separators=(",", ":"), default=str).encode("utf-8")
    ).hexdigest()


def _root(value: str | Path) -> Path:
    root = Path(value).expanduser().resolve()
    root.mkdir(parents=True, exist_ok=True)
    return root


def _global_root(value: str | Path | None = None) -> Path:
    configured = value or os.getenv("ADE_GLOBAL_RULES_ROOT")
    if configured:
        return _root(configured)
    return _root(Path.home() / ".ade")


def _store_path(root: Path) -> Path:
    return root / ".ade" / "rules.json"


def _load(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError(f"rule store must be an object: {path}")
    return payload


def _save(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def _normalize_paths(values: Iterable[str] | None) -> list[str]:
    result = []
    for value in values or []:
        pattern = str(value).strip().replace("\\", "/")
        if not pattern:
            continue
        if pattern.startswith("/") or ".." in Path(pattern).parts:
            raise ValueError("rule apply_paths must be workspace-relative glob patterns")
        result.append(pattern)
    return sorted(set(result))


def _path_matches(patterns: list[str], target_path: str | None) -> bool:
    if not patterns:
        return True
    if target_path is None:
        return False
    normalized = str(target_path).replace("\\", "/").lstrip("./")
    return any(fnmatch.fnmatch(normalized, pattern) for pattern in patterns)


def _specificity(patterns: list[str]) -> int:
    if not patterns:
        return 0
    return max(len(pattern.replace("*", "").replace("?", "")) for pattern in patterns)


class RuleStore:
    def __init__(
        self,
        project_root: str | Path,
        *,
        global_root: str | Path | None = None,
    ) -> None:
        self.project_root = _root(project_root)
        self.global_root = _global_root(global_root)

    def _root_for_scope(self, scope: str) -> Path:
        key = str(scope).casefold()
        if key == "project":
            return self.project_root
        if key == "global":
            return self.global_root
        raise ValueError("rule scope must be project or global")

    def save(
        self,
        name: str,
        content: str,
        *,
        scope: str = "project",
        priority: int = 0,
        apply_paths: Iterable[str] | None = None,
        enabled: bool = True,
        source: str = "managed",
    ) -> dict[str, Any]:
        if not _NAME.fullmatch(str(name)):
            raise ValueError("invalid rule name")
        text = str(content).strip()
        if not text:
            raise ValueError("rule content cannot be empty")
        patterns = _normalize_paths(apply_paths)
        root = self._root_for_scope(scope)
        path = _store_path(root)
        payload = _load(path)
        now = utc_now()
        rule = {
            "name": str(name),
            "scope": str(scope).casefold(),
            "priority": int(priority),
            "apply_paths": patterns,
            "enabled": bool(enabled),
            "content": text,
            "source": source,
            "updated_at": now,
        }
        rule["rule_fingerprint"] = _digest(
            {
                "name": rule["name"],
                "scope": rule["scope"],
                "priority": rule["priority"],
                "apply_paths": rule["apply_paths"],
                "enabled": rule["enabled"],
                "content": rule["content"],
            }
        )
        payload[str(name)] = rule
        _save(path, payload)
        return rule

    def set_enabled(self, name: str, enabled: bool, *, scope: str = "project") -> dict[str, Any]:
        root = self._root_for_scope(scope)
        path = _store_path(root)
        payload = _load(path)
        if name not in payload:
            raise KeyError(f"rule not found: {name}")
        existing = dict(payload[name])
        return self.save(
            name,
            str(existing["content"]),
            scope=scope,
            priority=int(existing.get("priority", 0)),
            apply_paths=list(existing.get("apply_paths") or []),
            enabled=enabled,
            source=str(existing.get("source") or "managed"),
        )

    def remove(self, name: str, *, scope: str = "project") -> dict[str, Any]:
        root = self._root_for_scope(scope)
        path = _store_path(root)
        payload = _load(path)
        existed = payload.pop(name, None)
        if existed is not None:
            _save(path, payload)
        return {"status": "PASS", "name": name, "scope": scope, "removed": existed is not None}

    def _managed(self, scope: str) -> list[dict[str, Any]]:
        root = self._root_for_scope(scope)
        return [
            dict(item)
            for _, item in sorted(_load(_store_path(root)).items())
        ]

    def _static_project_instructions(self) -> list[dict[str, Any]]:
        result: list[dict[str, Any]] = []
        for relative, priority in _STATIC_INSTRUCTIONS:
            path = self.project_root / relative
            if not path.is_file():
                continue
            content = path.read_text(encoding="utf-8", errors="replace").strip()
            if not content:
                continue
            item = {
                "name": f"static:{relative}",
                "scope": "project",
                "priority": priority,
                "apply_paths": [],
                "enabled": True,
                "content": content,
                "source": relative,
                "path": str(path),
                "managed": False,
            }
            item["rule_fingerprint"] = _digest(item)
            result.append(item)
        return result

    def list(self, *, include_static: bool = True) -> list[dict[str, Any]]:
        rules = [*self._managed("global"), *self._managed("project")]
        if include_static:
            rules.extend(self._static_project_instructions())
        rules.sort(
            key=lambda item: (
                0 if item["scope"] == "global" else 1,
                int(item.get("priority", 0)),
                item["name"],
            )
        )
        return rules

    def resolve(
        self,
        *,
        target_path: str | None = None,
    ) -> dict[str, Any]:
        candidates = []
        for item in self.list(include_static=True):
            if not item.get("enabled", True):
                continue
            patterns = list(item.get("apply_paths") or [])
            if not _path_matches(patterns, target_path):
                continue
            candidates.append(
                {
                    **item,
                    "path_specificity": _specificity(patterns),
                    "precedence": {
                        "scope": 0 if item["scope"] == "global" else 1,
                        "priority": int(item.get("priority", 0)),
                        "path_specificity": _specificity(patterns),
                    },
                }
            )
        candidates.sort(
            key=lambda item: (
                item["precedence"]["scope"],
                item["precedence"]["priority"],
                item["precedence"]["path_specificity"],
                item["name"],
            )
        )
        resolution = {
            "target_path": target_path,
            "rules": candidates,
            "content": [item["content"] for item in candidates],
            "policy_effect": "instructions_only_tool_policy_remains_authoritative",
        }
        return {
            "status": "PASS",
            **resolution,
            "resolution_fingerprint": _digest(
                [
                    (item["name"], item["scope"], item["rule_fingerprint"])
                    for item in candidates
                ]
            ),
        }

    def inspect(self, name: str, *, scope: str | None = None) -> dict[str, Any]:
        matches = [
            item
            for item in self.list(include_static=True)
            if item["name"] == name and (scope is None or item["scope"] == scope)
        ]
        if not matches:
            raise KeyError(f"rule not found: {name}")
        return matches[-1]
