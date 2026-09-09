"""Validated ADE plugin bundles: skills, agents, commands, MCP declarations and hooks."""

from __future__ import annotations

from dataclasses import dataclass
from hashlib import sha256
import json
from pathlib import Path
import re
import shutil
from typing import Any

import yaml

from agentic_data_platform.plugins.manager import PluginManager


_NAME = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,79}$")
_VERSION = re.compile(r"^[0-9]+\.[0-9]+\.[0-9]+(?:[-+][A-Za-z0-9._-]+)?$")
_MANIFEST_NAMES = ("ade-plugin.yml", "ade-plugin.yaml", "plugin.yml", "plugin.yaml")
_FILE_CONTRIBUTIONS = ("skills", "agents", "commands", "mcp")
_ALLOWED_HOOK_ACTIONS = {"allow", "block", "modify"}


@dataclass(frozen=True)
class PluginBundle:
    name: str
    version: str
    description: str
    root: Path
    manifest_path: Path
    manifest: dict[str, Any]
    checksums: dict[str, str]

    def public(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "version": self.version,
            "description": self.description,
            "root": str(self.root),
            "manifest_path": str(self.manifest_path),
            "checksums": dict(self.checksums),
            "contributions": dict(self.manifest.get("contributions") or {}),
        }


def _manifest_path(root: Path) -> Path:
    for name in _MANIFEST_NAMES:
        path = root / name
        if path.is_file():
            return path
    raise FileNotFoundError(f"plugin manifest not found under {root}")


def _safe_path(root: Path, raw: str) -> Path:
    relative = Path(str(raw))
    if relative.is_absolute() or ".." in relative.parts:
        raise ValueError(f"plugin contribution path must be relative and contained: {raw}")
    resolved = (root / relative).resolve()
    base = root.resolve()
    if resolved != base and base not in resolved.parents:
        raise ValueError(f"plugin contribution escapes bundle root: {raw}")
    if not resolved.exists():
        raise FileNotFoundError(f"plugin contribution not found: {raw}")
    return resolved


def _checksum(path: Path) -> str:
    digest = sha256()
    if path.is_file():
        digest.update(path.read_bytes())
        return digest.hexdigest()
    for item in sorted(candidate for candidate in path.rglob("*") if candidate.is_file()):
        digest.update(item.relative_to(path).as_posix().encode("utf-8"))
        digest.update(item.read_bytes())
    return digest.hexdigest()


def _match(payload: dict[str, Any], match: dict[str, Any]) -> bool:
    for key, expected in match.items():
        actual = payload.get(key)
        options = expected if isinstance(expected, list) else [expected]
        normalized = {str(item).casefold() for item in options}
        if "*" in normalized:
            continue
        if str(actual).casefold() not in normalized:
            return False
    return True


class PluginBundleService:
    """Install and activate project-scoped ADE bundles without arbitrary installer code."""

    def __init__(self, project_root: str | Path) -> None:
        self.project_root = Path(project_root).expanduser().resolve()
        self.install_root = self.project_root / ".ade" / "plugins"

    def validate(self, source: str | Path) -> dict[str, Any]:
        root = Path(source).expanduser().resolve()
        if not root.is_dir():
            raise NotADirectoryError(root)
        manifest_path = _manifest_path(root)
        raw = yaml.safe_load(manifest_path.read_text()) or {}
        if not isinstance(raw, dict):
            raise ValueError("plugin manifest must be an object")

        name = str(raw.get("name") or "").strip()
        version = str(raw.get("version") or "").strip()
        description = str(raw.get("description") or "").strip()
        if not _NAME.fullmatch(name):
            raise ValueError("plugin name must be a safe identifier")
        if not _VERSION.fullmatch(version):
            raise ValueError("plugin version must use semantic x.y.z form")
        if not description:
            raise ValueError("plugin description is required")

        contributions = raw.get("contributions") or {}
        if not isinstance(contributions, dict):
            raise ValueError("plugin contributions must be an object")

        checksums: dict[str, str] = {}
        normalized: dict[str, Any] = {}
        for kind in _FILE_CONTRIBUTIONS:
            items = contributions.get(kind) or []
            if not isinstance(items, list):
                raise ValueError(f"plugin contributions.{kind} must be a list")
            normalized_items: list[str] = []
            for item in items:
                path = _safe_path(root, str(item))
                if kind == "skills":
                    skill_file = path / "SKILL.md" if path.is_dir() else path
                    if skill_file.name != "SKILL.md" or not skill_file.is_file():
                        raise ValueError(f"skill contribution must contain SKILL.md: {item}")
                elif kind == "agents" and (not path.is_file() or path.suffix.casefold() != ".md"):
                    raise ValueError(f"agent contribution must be Markdown: {item}")
                elif kind == "commands" and not path.is_file():
                    raise ValueError(f"command contribution must be a file: {item}")
                elif kind == "mcp" and (not path.is_file() or path.suffix.casefold() not in {".json", ".yml", ".yaml"}):
                    raise ValueError(f"MCP contribution must be JSON/YAML: {item}")
                relative = path.relative_to(root).as_posix()
                normalized_items.append(relative)
                checksums[relative] = _checksum(path)
            normalized[kind] = normalized_items

        hooks = contributions.get("hooks") or []
        if not isinstance(hooks, list):
            raise ValueError("plugin contributions.hooks must be a list")
        normalized_hooks = []
        for index, hook in enumerate(hooks):
            if not isinstance(hook, dict):
                raise ValueError(f"hook {index} must be an object")
            event = str(hook.get("hook") or "")
            action = str(hook.get("action") or "allow").casefold()
            if event not in PluginManager.SUPPORTED_HOOKS:
                raise ValueError(f"unsupported hook event: {event}")
            if event not in PluginManager.ENFORCEABLE_HOOKS and action != "allow":
                raise ValueError(f"non-enforceable hook may only observe/allow: {event}")
            if action not in _ALLOWED_HOOK_ACTIONS:
                raise ValueError(f"unsupported hook action: {action}")
            match = hook.get("match") or {}
            if not isinstance(match, dict):
                raise ValueError(f"hook {index} match must be an object")
            updates = hook.get("updates") or {}
            if action == "modify" and not isinstance(updates, dict):
                raise ValueError(f"hook {index} updates must be an object")
            normalized_hooks.append({
                "hook": event,
                "action": action,
                "match": dict(match),
                "reason": str(hook.get("reason") or ""),
                "updates": dict(updates) if isinstance(updates, dict) else {},
            })
        normalized["hooks"] = normalized_hooks

        normalized_manifest = {
            **raw,
            "name": name,
            "version": version,
            "description": description,
            "contributions": normalized,
        }
        checksums[manifest_path.relative_to(root).as_posix()] = _checksum(manifest_path)
        return {
            "status": "PASS",
            "bundle": PluginBundle(
                name,
                version,
                description,
                root,
                manifest_path,
                normalized_manifest,
                checksums,
            ).public(),
        }

    def install(self, source: str | Path, *, overwrite: bool = False) -> dict[str, Any]:
        validated = self.validate(source)["bundle"]
        source_root = Path(validated["root"])
        destination = self.install_root / validated["name"]
        if destination.exists():
            if not overwrite:
                raise FileExistsError(f"plugin already installed: {validated['name']}")
            shutil.rmtree(destination)
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copytree(source_root, destination)
        state = {
            "name": validated["name"],
            "version": validated["version"],
            "installed_at": datetime_utc(),
            "active": False,
            "source_checksums": validated["checksums"],
        }
        (destination / ".ade-plugin-state.json").write_text(json.dumps(state, indent=2, sort_keys=True) + "\n")
        return self.inspect(validated["name"])

    def inspect(self, name: str) -> dict[str, Any]:
        root = self.install_root / name
        validated = self.validate(root)["bundle"]
        state_path = root / ".ade-plugin-state.json"
        state = json.loads(state_path.read_text()) if state_path.is_file() else {}
        return {
            "status": "PASS",
            **validated,
            "active": bool(state.get("active", False)),
            "installed_at": state.get("installed_at"),
        }

    def list(self) -> list[dict[str, Any]]:
        if not self.install_root.is_dir():
            return []
        items = []
        for folder in sorted(path for path in self.install_root.iterdir() if path.is_dir()):
            try:
                items.append(self.inspect(folder.name))
            except (ValueError, FileNotFoundError, NotADirectoryError) as exc:
                items.append({
                    "status": "FAIL",
                    "name": folder.name,
                    "error": f"{type(exc).__name__}: {exc}",
                })
        return items

    def _register_hooks(self, name: str, plugins: PluginManager) -> int:
        installed = self.inspect(name)
        contributions = installed["contributions"]
        plugins.unregister_plugin(name)
        registered_hooks = 0
        for hook in contributions.get("hooks", []):
            event = hook["hook"]
            action = hook["action"]
            match = dict(hook.get("match") or {})
            reason = str(hook.get("reason") or "")
            updates = dict(hook.get("updates") or {})

            def handler(
                payload: dict[str, Any],
                *,
                action=action,
                match=match,
                reason=reason,
                updates=updates,
            ):
                if not _match(payload, match):
                    return {"action": "allow"}
                if action == "block":
                    return {"action": "block", "reason": reason or f"blocked by plugin {name}"}
                if action == "modify":
                    return {"action": "modify", "updates": updates}
                return {"action": "allow"}

            plugins.register(name, event, handler)
            registered_hooks += 1
        return registered_hooks

    def load_active_hooks(self, plugins: PluginManager) -> dict[str, Any]:
        loaded: list[str] = []
        failed: list[dict[str, str]] = []
        for item in self.list():
            if item.get("status") != "PASS" or not item.get("active"):
                continue
            name = str(item["name"])
            try:
                self._register_hooks(name, plugins)
                loaded.append(name)
            except Exception as exc:
                failed.append({"name": name, "error": f"{type(exc).__name__}: {exc}"})
        return {
            "status": "FAIL" if failed else "PASS",
            "loaded": loaded,
            "failed": failed,
        }

    def activate(
        self,
        name: str,
        *,
        plugins: PluginManager | None = None,
        overwrite: bool = False,
    ) -> dict[str, Any]:
        installed = self.inspect(name)
        root = Path(installed["root"])
        contributions = installed["contributions"]
        materialized: dict[str, list[str]] = {kind: [] for kind in _FILE_CONTRIBUTIONS}

        destinations = {
            "skills": self.project_root / ".ade" / "skills",
            "agents": self.project_root / ".ade" / "agents",
            "commands": self.project_root / ".ade" / "commands",
            "mcp": self.project_root / ".ade" / "mcp",
        }

        for kind in _FILE_CONTRIBUTIONS:
            destination_root = destinations[kind]
            destination_root.mkdir(parents=True, exist_ok=True)
            for relative in contributions.get(kind, []):
                source = _safe_path(root, relative)
                if kind == "skills":
                    skill_file = source / "SKILL.md" if source.is_dir() else source
                    destination = destination_root / skill_file.parent.name
                    if destination.exists():
                        if not overwrite:
                            raise FileExistsError(f"plugin activation collision: {destination}")
                        shutil.rmtree(destination)
                    destination.mkdir(parents=True, exist_ok=True)
                    shutil.copy2(skill_file, destination / "SKILL.md")
                else:
                    destination = destination_root / source.name
                    if destination.exists() and not overwrite:
                        raise FileExistsError(f"plugin activation collision: {destination}")
                    shutil.copy2(source, destination)
                materialized[kind].append(str(destination.relative_to(self.project_root)))

        registered_hooks = self._register_hooks(name, plugins) if plugins is not None else 0

        state_path = root / ".ade-plugin-state.json"
        state = json.loads(state_path.read_text()) if state_path.is_file() else {}
        state.update({"active": True, "activated_at": datetime_utc()})
        state_path.write_text(json.dumps(state, indent=2, sort_keys=True) + "\n")
        return {
            "status": "PASS",
            "name": name,
            "version": installed["version"],
            "active": True,
            "materialized": materialized,
            "registered_hooks": registered_hooks,
        }

    def remove(self, name: str, *, plugins: PluginManager | None = None) -> dict[str, Any]:
        root = self.install_root / name
        if not root.exists():
            return {"status": "PASS", "name": name, "removed": False}
        if plugins is not None:
            plugins.unregister_plugin(name)
        shutil.rmtree(root)
        return {"status": "PASS", "name": name, "removed": True}


def datetime_utc() -> str:
    from datetime import datetime, timezone

    return datetime.now(timezone.utc).isoformat()
