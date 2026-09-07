from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field

from agentic_data_platform.migrations.checkpoints import CheckpointStore
from agentic_data_platform.migrations.models import MigrationCheckpoint, MigrationObject, MigrationStatus, MigrationWave

MigrationAction = Callable[[MigrationObject, str], dict[str, object] | None]


@dataclass(frozen=True)
class WaveExecutionReport:
    wave_id: str
    status: MigrationStatus
    completed_objects: tuple[str, ...] = ()
    skipped_objects: tuple[str, ...] = ()
    failed_object: str | None = None
    evidence: dict[str, object] = field(default_factory=dict)


class MigrationWaveExecutor:
    phases = ("DDL", "VALIDATE_DDL", "TRANSFER", "RECONCILE")

    def __init__(self, checkpoints: CheckpointStore) -> None:
        self.checkpoints = checkpoints

    @staticmethod
    def ordered_objects(wave: MigrationWave) -> tuple[MigrationObject, ...]:
        remaining = {item.name: item for item in wave.objects}
        ordered: list[MigrationObject] = []
        while remaining:
            ready = sorted((item for item in remaining.values() if all(dep not in remaining for dep in item.dependencies)), key=lambda item: item.name)
            if not ready:
                raise ValueError("migration wave has a dependency cycle or a dependency outside the wave")
            for item in ready:
                ordered.append(item)
                remaining.pop(item.name)
        return tuple(ordered)

    def execute(self, wave: MigrationWave, action: MigrationAction) -> WaveExecutionReport:
        completed: list[str] = []
        skipped: list[str] = []
        try:
            objects = self.ordered_objects(wave)
        except ValueError as exc:
            return WaveExecutionReport(wave.wave_id, MigrationStatus.BLOCKED, evidence={"error": str(exc)})
        for obj in objects:
            all_complete = True
            for phase in self.phases:
                if self.checkpoints.completed(wave.wave_id, obj.object_id, phase):
                    continue
                all_complete = False
                try:
                    evidence = action(obj, phase) or {}
                    self.checkpoints.save(MigrationCheckpoint(wave.wave_id, obj.object_id, phase, evidence=evidence))
                except Exception as exc:
                    self.checkpoints.save(MigrationCheckpoint(wave.wave_id, obj.object_id, phase, status="FAILED", evidence={"error": str(exc)}))
                    return WaveExecutionReport(wave.wave_id, MigrationStatus.FAILED, tuple(completed), tuple(skipped), obj.name, {"phase": phase, "error": str(exc)})
            if all_complete:
                skipped.append(obj.name)
            else:
                completed.append(obj.name)
        return WaveExecutionReport(wave.wave_id, MigrationStatus.COMPLETED, tuple(completed), tuple(skipped))

    def resume_wave(self, wave: MigrationWave, action: MigrationAction) -> WaveExecutionReport:
        return self.execute(wave, action)
