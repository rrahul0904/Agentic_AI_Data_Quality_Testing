from __future__ import annotations

import re
from dataclasses import dataclass
from enum import Enum


class DriftCategory(str, Enum):
    SAFE = "safe"
    WARNING = "warning"
    BREAKING = "breaking"
    UNKNOWN = "unknown"


@dataclass(frozen=True)
class SchemaColumn:
    name: str
    data_type: str
    nullable: bool = True
    default: str | None = None


@dataclass(frozen=True)
class SchemaChange:
    column: str
    category: DriftCategory
    detail: str


@dataclass(frozen=True)
class SchemaChangeReport:
    changes: tuple[SchemaChange, ...]

    @property
    def breaking(self) -> tuple[SchemaChange, ...]:
        return tuple(item for item in self.changes if item.category is DriftCategory.BREAKING)


class SchemaChangeAnalyzer:
    @staticmethod
    def _varchar_length(data_type: str) -> int | None:
        match = re.fullmatch(r"(?:VAR)?CHAR\s*\(\s*(\d+)\s*\)", data_type.upper())
        return int(match.group(1)) if match else None

    @classmethod
    def _type_change(cls, before: SchemaColumn, after: SchemaColumn) -> SchemaChange:
        if before.data_type.upper() == after.data_type.upper():
            if before.nullable and not after.nullable:
                return SchemaChange(after.name, DriftCategory.BREAKING, "column changed from nullable to required")
            if not before.nullable and after.nullable:
                return SchemaChange(after.name, DriftCategory.SAFE, "column changed from required to nullable")
            return SchemaChange(after.name, DriftCategory.SAFE, "no material change")
        old, new = before.data_type.upper(), after.data_type.upper()
        if old in {"INT", "INTEGER"} and new in {"BIGINT", "NUMBER"}:
            return SchemaChange(after.name, DriftCategory.SAFE, f"widened {old} to {new}")
        if old == "BIGINT" and new in {"INT", "INTEGER"}:
            return SchemaChange(after.name, DriftCategory.BREAKING, f"narrowed {old} to {new}")
        old_length, new_length = cls._varchar_length(old), cls._varchar_length(new)
        if old_length is not None and new_length is not None:
            category = DriftCategory.SAFE if new_length >= old_length else DriftCategory.WARNING
            return SchemaChange(after.name, category, f"VARCHAR length changed from {old_length} to {new_length}")
        return SchemaChange(after.name, DriftCategory.UNKNOWN, f"type changed from {old} to {new}")

    @classmethod
    def compare(cls, before: list[SchemaColumn], after: list[SchemaColumn]) -> SchemaChangeReport:
        old = {item.name.lower(): item for item in before}
        new = {item.name.lower(): item for item in after}
        changes: list[SchemaChange] = []
        for name in sorted(old.keys() - new.keys()):
            changes.append(SchemaChange(old[name].name, DriftCategory.BREAKING, "column removed"))
        for name in sorted(new.keys() - old.keys()):
            item = new[name]
            category = DriftCategory.SAFE if item.nullable or item.default is not None else DriftCategory.BREAKING
            changes.append(SchemaChange(item.name, category, "column added" if category is DriftCategory.SAFE else "required column added without default"))
        for name in sorted(old.keys() & new.keys()):
            change = cls._type_change(old[name], new[name])
            if change.detail != "no material change":
                changes.append(change)
        return SchemaChangeReport(tuple(changes))
