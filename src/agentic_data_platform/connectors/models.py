from __future__ import annotations

from dataclasses import dataclass, field
from decimal import Decimal
from typing import Any


@dataclass(frozen=True)
class ColumnMetadata:
    name: str
    data_type: str
    nullable: bool = True
    ordinal_position: int | None = None
    precision: int | None = None
    scale: int | None = None
    default: str | None = None


@dataclass(frozen=True)
class SchemaMetadata:
    name: str
    catalog: str | None = None


@dataclass(frozen=True)
class TableMetadata:
    name: str
    schema: str
    catalog: str | None = None
    object_type: str = "table"
    columns: tuple[ColumnMetadata, ...] = ()
    comment: str | None = None

    @property
    def qualified_name(self) -> str:
        return ".".join(part for part in (self.catalog, self.schema, self.name) if part)


@dataclass(frozen=True)
class QueryResult:
    rows: tuple[dict[str, Any], ...] = ()
    columns: tuple[str, ...] = ()
    query_id: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class DryRunResult:
    valid: bool
    estimated_bytes: int | None = None
    estimated_cost: Decimal | None = None
    warnings: tuple[str, ...] = ()
    metadata: dict[str, Any] = field(default_factory=dict)
