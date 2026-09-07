"""Deterministic memory, training and skill context selection for agent sessions."""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable

from agentic_data_platform.memory.store import MemoryStore
from agentic_data_platform.skills.registry import Skill, SkillRegistry


_WORD = re.compile(r"[A-Za-z0-9_]{2,}")


def _terms(text: str) -> set[str]:
    return {item.casefold() for item in _WORD.findall(text)}


def _score(query: str, content: str, tags: Iterable[str] = ()) -> int:
    wanted = _terms(query)
    if not wanted:
        return 0
    body = _terms(content)
    tag_terms = {term for tag in tags for term in _terms(str(tag))}
    return len(wanted & body) + 3 * len(wanted & tag_terms)


@dataclass(frozen=True)
class ContextSelection:
    messages: tuple[dict[str, Any], ...]
    memory_ids: tuple[str, ...]
    training_ids: tuple[str, ...]
    skill_names: tuple[str, ...]

    def metadata(self) -> dict[str, Any]:
        return {
            "memory_ids": list(self.memory_ids),
            "training_ids": list(self.training_ids),
            "skill_names": list(self.skill_names),
        }


class ContextSourceManager:
    """Select bounded project context without injecting every stored item."""

    def __init__(
        self,
        memory: MemoryStore | None = None,
        *,
        skill_registry: SkillRegistry | None = None,
        max_memories: int = 6,
        max_training: int = 6,
        max_skills: int = 8,
    ) -> None:
        self.memory = memory
        self.skill_registry = skill_registry
        self.max_memories = max_memories
        self.max_training = max_training
        self.max_skills = max_skills

    def select(
        self,
        query: str,
        *,
        project_id: str | None = None,
        project_root: str | Path | None = None,
    ) -> ContextSelection:
        messages: list[dict[str, Any]] = []
        memory_ids: list[str] = []
        training_ids: list[str] = []
        skill_names: list[str] = []

        if self.memory is not None:
            memories = self.memory.list_memories(project_id=project_id, limit=500)
            ranked_memories = sorted(
                (
                    (_score(query, item["content"], item.get("tags", ())), item)
                    for item in memories
                ),
                key=lambda pair: (-pair[0], str(pair[1].get("updated_at", ""))),
            )
            selected_memories = [
                item for score, item in ranked_memories if score > 0
            ][: self.max_memories]
            if selected_memories:
                memory_ids = [str(item["memory_id"]) for item in selected_memories]
                messages.append(
                    {
                        "role": "system",
                        "content": "Relevant project memory:\n"
                        + "\n".join(f"- {item['content']}" for item in selected_memories),
                        "context_source": "memory",
                        "context_ids": memory_ids,
                    }
                )

            training = self.memory.list_training(project_id=project_id)
            ranked_training = sorted(
                (
                    (
                        _score(
                            query,
                            " ".join(
                                str(value)
                                for value in (
                                    item.get("kind"),
                                    item.get("content"),
                                    item.get("source"),
                                )
                                if value
                            ),
                            (),
                        ),
                        item,
                    )
                    for item in training
                ),
                key=lambda pair: (-pair[0], -int(pair[1].get("applied_count", 0))),
            )
            selected_training = [
                item for score, item in ranked_training if score > 0
            ][: self.max_training]
            if selected_training:
                training_ids = [str(item["training_id"]) for item in selected_training]
                messages.append(
                    {
                        "role": "system",
                        "content": "Relevant teammate training and project standards:\n"
                        + "\n".join(f"- {item['content']}" for item in selected_training),
                        "context_source": "training",
                        "context_ids": training_ids,
                    }
                )
                for training_id in training_ids:
                    self.memory.mark_training_applied(training_id)

        registry = self.skill_registry
        if registry is None and project_root is not None:
            registry = SkillRegistry.discover(project_root)
        if registry is not None:
            selected_skills: list[Skill] = []
            if project_root is not None:
                selected_skills.extend(registry.auto_load(project_root))
            for skill in registry.list():
                if skill in selected_skills:
                    continue
                if _score(query, skill.name + " " + skill.description + " " + skill.body) > 0:
                    selected_skills.append(skill)
            selected_skills = selected_skills[: self.max_skills]
            if selected_skills:
                skill_names = [item.name for item in selected_skills]
                messages.append(
                    {
                        "role": "system",
                        "content": "Active skills:\n"
                        + "\n\n".join(
                            f"## {item.name}\n{item.body}" for item in selected_skills
                        ),
                        "context_source": "skills",
                        "context_ids": skill_names,
                    }
                )

        return ContextSelection(
            messages=tuple(messages),
            memory_ids=tuple(memory_ids),
            training_ids=tuple(training_ids),
            skill_names=tuple(skill_names),
        )
