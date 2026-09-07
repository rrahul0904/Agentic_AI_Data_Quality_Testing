# Reverse engineering notes from the supplied demo

## Observed product behavior

The recording shows a terminal-based coding agent launched with a named BigQuery→Redshift converter agent. The operator provides a dbt repository path, a destination folder, and conversion invariants: preserve processed-table attributes and ensure Redshift sort keys exist in the model projection.

The agent exposes file listing/read/write and shell tools, creates a plan before conversion, and requests approval before writes and shell commands. It converts one model at a time, runs `dbt compile`, reads failures, and attempts remediation. The demo also exposes two important failure modes: placing converted models beneath the active dbt `models/` tree creates duplicate resource names, and missing source definitions can make compile validation fail independently of SQL dialect conversion.

## Reconstructed workflow

1. Resolve repository root and discover dbt models.
2. Inspect model SQL and dbt config.
3. Build a model-level conversion plan.
4. Rewrite safe dialect differences deterministically.
5. Enforce Redshift physical-design invariants (sort/dist keys).
6. Refuse to guess source expressions for missing projected keys unless a hint/semantic agent supplies one.
7. Write to a sibling output tree only after explicit approval.
8. Validate in a temporary cloned dbt workspace.
9. Surface compile failures as typed findings: conversion error, project configuration error, missing source, missing macro/package, or environment/credential error.
10. Produce a machine-readable and human-readable migration report.

## Improvements over the demo

- Never write converted files under the active source model tree by default.
- Never delete/rename original models for validation.
- Dry-run by default; `--approve` is required to write.
- Deterministic transformations happen before any LLM step.
- Missing sort-key expressions block the model instead of hallucinating a column source.
- Missing dbt sources are reported rather than silently invented with placeholder database/schema names.
- Every transformation has a rule ID and audit record.
