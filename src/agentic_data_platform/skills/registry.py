from __future__ import annotations

import fnmatch
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable

import yaml


@dataclass(frozen=True)
class Skill:
    name: str
    description: str
    body: str
    path: Path
    always_apply: bool = False
    apply_paths: tuple[str, ...] = ()
    metadata: dict[str, Any] | None = None


def parse_skill(path: str | Path) -> Skill:
    source = Path(path).expanduser().resolve()
    text = source.read_text()
    metadata: dict[str, Any] = {}
    body = text
    if text.startswith("---"):
        parts = text.split("---", 2)
        if len(parts) == 3:
            metadata = yaml.safe_load(parts[1]) or {}
            body = parts[2]
    apply_paths = metadata.get("applyPaths") or ()
    if isinstance(apply_paths, str):
        apply_paths = (apply_paths,)
    return Skill(
        name=str(metadata.get("name") or source.parent.name),
        description=str(metadata.get("description") or ""),
        body=body.strip(),
        path=source,
        always_apply=bool(metadata.get("alwaysApply", False)),
        apply_paths=tuple(str(item) for item in apply_paths),
        metadata=metadata,
    )


class SkillRegistry:
    """Discover project/global skills and resolve deterministic auto-load rules."""

    def __init__(self, skills: Iterable[Skill] = ()) -> None:
        self._skills = {skill.name: skill for skill in skills}

    @staticmethod
    def discovery_roots(
        project_root: str | Path,
        *,
        global_root: str | Path | None = None,
        custom_paths: Iterable[str | Path] = (),
    ) -> tuple[Path, ...]:
        root = Path(project_root).expanduser().resolve()
        paths = [
            root / ".opencode" / "skills",
            root / ".altimate-code" / "skill",
            root / ".altimate-code" / "skills",
            Path(global_root).expanduser().resolve() if global_root else Path.home() / ".altimate-code" / "skills",
        ]
        paths.extend(Path(item).expanduser().resolve() for item in custom_paths)
        unique: list[Path] = []
        seen: set[str] = set()
        for item in paths:
            key = str(item)
            if key not in seen:
                unique.append(item)
                seen.add(key)
        return tuple(unique)

    @classmethod
    def discover(
        cls,
        project_root: str | Path,
        *,
        global_root: str | Path | None = None,
        custom_paths: Iterable[str | Path] = (),
    ) -> "SkillRegistry":
        found: dict[str, Skill] = {}
        for base in cls.discovery_roots(project_root, global_root=global_root, custom_paths=custom_paths):
            if not base.is_dir():
                continue
            for path in sorted(base.glob("*/SKILL.md")):
                skill = parse_skill(path)
                found[skill.name] = skill
        return cls(found.values())

    def list(self) -> list[Skill]:
        return [self._skills[name] for name in sorted(self._skills)]

    def get(self, name: str) -> Skill:
        try:
            return self._skills[name]
        except KeyError as exc:
            raise KeyError(f"skill not found: {name}") from exc

    def auto_load(self, project_root: str | Path) -> list[Skill]:
        root = Path(project_root).expanduser().resolve()
        relative_files = [
            path.relative_to(root).as_posix()
            for path in root.rglob("*")
            if path.is_file() and ".git" not in path.parts
        ]
        selected: list[Skill] = []
        for skill in self.list():
            if skill.always_apply:
                selected.append(skill)
                continue
            if skill.apply_paths and any(
                fnmatch.fnmatch(relative_path, pattern)
                for pattern in skill.apply_paths
                for relative_path in relative_files
            ):
                selected.append(skill)
        return selected

    def create(
        self,
        root: str | Path,
        name: str,
        description: str,
        body: str,
        *,
        always_apply: bool = False,
        apply_paths: Iterable[str] = (),
    ) -> Path:
        safe = name.strip().replace(" ", "-")
        if not safe or any(token in safe for token in ("/", "\\", "..")):
            raise ValueError("invalid skill name")
        folder = Path(root).expanduser().resolve() / safe
        folder.mkdir(parents=True, exist_ok=False)
        path = folder / "SKILL.md"
        metadata = {
            "name": name,
            "description": description,
            "alwaysApply": always_apply,
            "applyPaths": list(apply_paths),
        }
        path.write_text(
            "---\n"
            + yaml.safe_dump(metadata, sort_keys=False).strip()
            + "\n---\n\n"
            + body.strip()
            + "\n"
        )
        skill = parse_skill(path)
        self._skills[skill.name] = skill
        return path

    def remove(self, name: str, *, delete_file: bool = False) -> bool:
        skill = self._skills.pop(name, None)
        if skill is None:
            return False
        if delete_file:
            skill.path.unlink(missing_ok=True)
            try:
                skill.path.parent.rmdir()
            except OSError:
                pass
        return True
