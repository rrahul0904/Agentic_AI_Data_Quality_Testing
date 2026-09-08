"""Partition strategy contracts used by scalable Data Diff planning."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol, Sequence



@dataclass(frozen=True)
class PartitionPlan:
    strategy: str
    key_columns: tuple[str, ...]
    warehouse_pushdown: bool
    reason: str


class PartitionStrategy(Protocol):
    name: str

    def plan(self, key_columns: Sequence[str]) -> PartitionPlan: ...


@dataclass(frozen=True)
class NumericRangePartitioner:
    name: str = "NUMERIC_RANGE"

    def plan(self, key_columns: Sequence[str]) -> PartitionPlan:
        return PartitionPlan(self.name, tuple(key_columns), True, "numeric min/max ranges support native predicate pruning")


@dataclass(frozen=True)
class TimestampRangePartitioner:
    name: str = "TIMESTAMP_RANGE"

    def plan(self, key_columns: Sequence[str]) -> PartitionPlan:
        return PartitionPlan(self.name, tuple(key_columns), True, "timestamp ranges support native predicate pruning")


@dataclass(frozen=True)
class LexicographicPartitioner:
    name: str = "LEXICOGRAPHIC"

    def plan(self, key_columns: Sequence[str]) -> PartitionPlan:
        return PartitionPlan(self.name, tuple(key_columns), True, "warehouse-derived string boundaries preserve lexicographic range pruning")


@dataclass(frozen=True)
class HashBucketPartitioner:
    name: str = "HASH_BUCKET"

    def plan(self, key_columns: Sequence[str]) -> PartitionPlan:
        return PartitionPlan(self.name, tuple(key_columns), False, "stable MD5-prefix buckets bound cross-platform string comparisons")


@dataclass(frozen=True)
class CompoundKeyPartitioner(HashBucketPartitioner):
    name: str = "COMPOUND_KEY"


def strategy_catalog() -> tuple[PartitionStrategy, ...]:
    return (
        NumericRangePartitioner(),
        TimestampRangePartitioner(),
        LexicographicPartitioner(),
        HashBucketPartitioner(),
        CompoundKeyPartitioner(),
    )


def describe_strategy(name: str, key_columns: Sequence[str]) -> PartitionPlan:
    for strategy in strategy_catalog():
        if strategy.name == name.upper():
            return strategy.plan(key_columns)
    raise KeyError(name)
