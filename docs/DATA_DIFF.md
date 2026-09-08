# Data Diff production model

The connector-driven Data Diff engine supports profile, join, hash, cascade, schema/key/row, aggregate and reconciliation-oriented comparisons. Production behavior is pushdown-first and bounded.

## Correctness properties

Regression coverage verifies:

- empty tables and ordinary bounded tables;
- NULL key rows are placed in an explicit partition instead of being skipped by MIN/MAX range planning;
- duplicate-key row-hash multiplicity is preserved with multisets;
- nullable same-connector joins use presence sentinels rather than treating a NULL key as a missing side;
- composite and nonnumeric keys select hash/lexicographic strategies where supported;
- mixed changed/missing/extra keys and deterministic output ordering;
- bounded cross-warehouse fallback;
- query and transferred-hash row accounting;
- zero raw-row transfer for HASH_DIFF;
- fail-closed behavior when a partition cannot be bounded.

## Pushdown model

`PROFILE` transfers aggregates only. `HASH_DIFF` performs remote signatures and bounded row-hash reads for mismatching partitions. Same-connector `JOIN_DIFF` pushes a FULL OUTER JOIN into the warehouse.

The local benchmark builds data inside DuckDB using SQL range generation; it does not first create the complete input as Python objects.

## Recorded full local DuckDB benchmark

| Scale | Runtime | Partitions | Queries | Rows transferred | Raw rows transferred |
|---:|---:|---:|---:|---:|---:|
| 10K | ~0.121 s | 1 | 6 | 20,000 | 0 |
| 100K | ~0.422 s | 3 | 10 | 100,000 | 0 |
| 1M | ~2.758 s | 11 | 26 | 62,500 | 0 |
| 10M | ~28.725 s | 17 | 38 | 78,124 | 0 |

Peak process RSS was approximately 158 MB for that recorded local run. Runtime/RSS vary by runner.

```bash
PYTHONPATH=src python benchmarks/data_diff/run.py
```

Push CI intentionally runs only 10K/100K. A release benchmark commit or workflow dispatch activates full 10K→10M.

## 100M+ harness

`scripts/live_data_diff_100m.py` is a read-only external harness. It requires both sides to have at least 100,000,000 rows and records row counts, runtime, partition strategy, partition/query counts, rows transferred, and diff status.

Without configured qualifying external targets its truthful state is `SKIP_EXTERNAL` / `NOT_RUN`. A runnable harness is not a passed certification.
