"""Portable SQL AST summary used by policy and verification, not an execution engine."""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(frozen=True)
class SqlAst:
    dialect: str
    statement_type: str
    tables: tuple[str, ...] = ()
    columns: tuple[str, ...] = ()
    source_tables: tuple[str, ...] = ()
    target_tables: tuple[str, ...] = ()
    joins: tuple[str, ...] = ()
    ctes: tuple[str, ...] = ()
    functions: tuple[str, ...] = ()
    ddl_operations: tuple[str, ...] = ()
    dml_operations: tuple[str, ...] = ()
    errors: tuple[str, ...] = ()
    backend: str = "fallback"
    metadata: dict[str, object] = field(default_factory=dict)

    @property
    def parseable(self) -> bool:
        return not self.errors
