# Migrations

Wave 2 adds `MigrationWave`, `MigrationObject`, and `MigrationCheckpoint`. Objects are dependency ordered, and each object advances through DDL, DDL validation, transfer, and reconciliation. A successful phase is checkpointed; `resume_wave` skips completed phases. A failed object blocks all following work in that execution.

The wave executor accepts deterministic, host-supplied actions. It does not make connector calls or bypass `ToolRegistry`. Source/target metrics are compared by partition, so reconciliation receives aggregate metrics and hashes rather than full datasets.
