# NVIDIA Auto Ontology → Governed Semantic Platform

## Source evidence, observed 2026-11-08

Original LinkedIn short link: https://lnkd.in/p/gVF5Shyt

Canonical LinkedIn post: https://www.linkedin.com/posts/akshay-pachaar_nvidia-just-fixed-text-to-sqls-biggest-problem-share-7525181336886898688-6k0W/

Official GitHub source: https://github.com/NVIDIA/auto-ontology

The public LinkedIn page reported 14 comments and displayed 9 entries (including the author's repository link). Additional nested/hidden discussion was inaccessible. The referenced architecture graphic was not independently inspected. The LinkedIn author's product descriptions are claims, not verified execution outcomes. The NVIDIA GitHub README independently documents the core generate–human review–query workflow, architecture and Apache-2.0 source license.

## Identity and deduplication

This is a source-donor and implementation slice, not a new standalone product or newly allocated reverse-engineering project ID. It belongs to the existing Governed Agentic Analytics / Snowflake Semantic Platform in rrahul0904/Agentic_AI_Data_Quality_Testing. The canonical Snowflake semantic metric contract remains authoritative, and this overlay must not create a second metric source of truth.

Related: draft PR #39 for the Drizzle Cube semantic runtime; reconcile compiler abstractions before expanding text-to-SQL generation.

## Social discussion findings

| Observed concern or feature request | Our acceptance implication |
| --- | --- |
| Historical SQL may encode obsolete definitions | No automatic certification from query-history frequency |
| Changing schema or meaning can invalidate certified terms | Pin reviews to source fingerprint and definition hash; recertify on drift |
| Unenforced foreign keys make inferred joins uncertain | Record inferred joins as hypotheses; require explicit review |
| Missing business concepts should not yield fabricated answers | Fail closed when a required concept is unavailable |
| Compare with Snowflake semantic views | Benchmark against the existing governed semantic view on identical questions |
| Context retrieval token cost and accuracy | Measure latency, tokens and outcomes in later evaluation |
| Existing data documentation may already be adequate | Import and preserve customer-owned semantic definitions |
| SQL filter repair behavior is unclear | Do not add ungated automatic repair in first slice |

These are observations of comments, not proof of NVIDIA implementation deficiencies.

## Implemented Phase 1

The new Python module src/agentic_data_platform/semantic/ontology_review.py provides:
- Source-inventory SHA-256 fingerprinting (caller supplies independent live metadata).
- Candidate term labels that remain HYPOTHESIS, never auto-approved.
- Manual review receipts tied to resource definition and source fingerprint.
- Fail-closed term and relationship selection with explicit refusal reasons.
- Automatic staleness when reviewed definitions or source fingerprint changes.
- No SQL execution, copied UI, live connectors, NLP model calls or Docker.

Offline tests in tests/test_ontology_review.py cover 14 deterministic cases including unknown concepts, missing reviews, staleness and unreviewed joins.

Critical limitation: the reviewer name is supplied by the caller, not authenticated. REVIEW_RECORDED is a local ledger state, not independently verified enterprise certification. READY_FOR_SQL_VALIDATION is only permission to proceed to separate downstream policy checks; it is NOT SQL access authorization.

## REA roadmap

1. Read-only source profiling and scoped metadata adapters for Snowflake, Postgres, Databricks and DuckDB.
2. Authenticated reviewer identity, RBAC, immutable/versioned approvals and provenance evidence.
3. Canonical semantic contract import/export, with no duplication of metric calculation logic.
4. Join-cardinality and data-profiling evidence; bridge-table reviews.
5. SQL AST safety, governed query generation, bounded filter repair and refusal.
6. Existing MCP/CLI/API integration with policy checks and audit trace.
7. Independent semantic-parity comparison against Snowflake Cortex Analyst and verified query suite.
8. Measure hallucinated-metric rate, result parity, cost, latency, schema drift and security edge cases.
9. Explicit review gates before merging or deployment; no automatic deployment.

## Clean-room choices

MATCH: Ontology terms, semantic relationships, human review.

IMPROVE: Drift-aware fail-closed certification and source provenance.

NEW: Cross-consumer metric-parity and performance evaluation.

OMIT for now: NVIDIA UI reproduction, default NIM inference, Docker, deployments, live access.

Local verification receipt: 14/14 offline unit tests passed in a temporary prototype snapshot (2026-11-08). Live warehouse, connector, authentication and GitHub CI acceptance remain unverified. This branch must remain an unmerged draft until independent review.
