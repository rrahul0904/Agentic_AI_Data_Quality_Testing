from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum

from agentic_data_platform.models import new_id, utc_now


class MigrationStatus(str, Enum):
    DISCOVERED = "discovered"
    ASSESSED = "assessed"
    PLANNED = "planned"
    READY = "ready"
    RUNNING = "running"
    VERIFYING = "verifying"
    PASSED = "passed"
    FAILED = "failed"
    BLOCKED = "blocked"
    APPROVED = "approved"
    COMPLETED = "completed"


@dataclass(frozen=True)
class MigrationObject:
    name: str
    object_type: str = "table"
    dependencies: tuple[str, ...] = ()
    object_id: str = field(default_factory=lambda: new_id("mobj"))


@dataclass(frozen=True)
class MigrationWave:
    name: str
    objects: tuple[MigrationObject, ...]
    wave_id: str = field(default_factory=lambda: new_id("wave"))
    status: MigrationStatus = MigrationStatus.PLANNED
    created_at: str = field(default_factory=utc_now)


@dataclass(frozen=True)
class MigrationCheckpoint:
    wave_id: str
    object_id: str
    phase: str
    partition: str | None = None
    status: str = "COMPLETE"
    evidence: dict[str, object] = field(default_factory=dict)
    checkpoint_id: str = field(default_factory=lambda: new_id("ckpt"))
    created_at: str = field(default_factory=utc_now)
