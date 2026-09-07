from __future__ import annotations
from dataclasses import asdict, dataclass, field
from typing import Any
from agentic_data_platform.models import Platform, new_id

@dataclass(frozen=True)
class ColumnMapping:
    source_name: str
    source_type: str
    target_name: str
    target_type: str
    nullable: bool = True
    transformation: str | None = None

@dataclass(frozen=True)
class MigrationObject:
    source_name: str
    target_name: str
    object_type: str
    source_ddl: str
    target_ddl_candidate: str
    column_mappings: tuple[ColumnMapping, ...] = ()
    dependencies: tuple[str, ...] = ()

@dataclass(frozen=True)
class MigrationSpec:
    source_platform: Platform
    target_platform: Platform
    objects: tuple[MigrationObject, ...]
    data_movement_strategy: str = "batch"
    validation_rules: tuple[str, ...] = ("schema_parity", "row_count_parity")
    cutover_strategy: str = "validate_then_switch"
    rollback_strategy: str = "retain_source_and_revert_consumers"
    approval_requirements: tuple[str, ...] = ("production_mutation",)
    spec_id: str = field(default_factory=lambda: new_id("mspec"))

    def to_dict(self) -> dict[str, Any]:
        payload = asdict(self); payload["source_platform"] = self.source_platform.value; payload["target_platform"] = self.target_platform.value
        return payload
