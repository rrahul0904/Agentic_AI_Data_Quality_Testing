from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(frozen=True)
class ReconciliationPlan:
    key_columns: tuple[str, ...]
    partition_strategy: str = "range"
    metrics: tuple[str, ...] = ("row_count", "hash")


@dataclass(frozen=True)
class PartitionMetrics:
    partition: str
    row_count: int
    null_counts: dict[str, int] = field(default_factory=dict)
    distinct_counts: dict[str, int] = field(default_factory=dict)
    min_values: dict[str, object] = field(default_factory=dict)
    max_values: dict[str, object] = field(default_factory=dict)
    hash_value: str | None = None


@dataclass(frozen=True)
class PartitionReconciliation:
    partition: str
    passed: bool
    differences: dict[str, object]


def reconcile_partitions(source: list[PartitionMetrics], target: list[PartitionMetrics]) -> list[PartitionReconciliation]:
    target_by_partition = {item.partition: item for item in target}
    results: list[PartitionReconciliation] = []
    for left in source:
        right = target_by_partition.pop(left.partition, None)
        if right is None:
            results.append(PartitionReconciliation(left.partition, False, {"target": "missing"}))
            continue
        differences: dict[str, object] = {}
        for metric in ("row_count", "null_counts", "distinct_counts", "min_values", "max_values", "hash_value"):
            if getattr(left, metric) != getattr(right, metric):
                differences[metric] = {"source": getattr(left, metric), "target": getattr(right, metric)}
        results.append(PartitionReconciliation(left.partition, not differences, differences))
    results.extend(PartitionReconciliation(partition, False, {"source": "missing"}) for partition in sorted(target_by_partition))
    return results
