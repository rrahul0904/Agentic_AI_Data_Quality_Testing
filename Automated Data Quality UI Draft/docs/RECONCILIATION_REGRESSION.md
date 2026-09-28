# Reconciliation result and history regression (2026-09-23)

## Reproduced symptoms

- Null and duplicate checks could display `PASS` beside “Comparison not completed,” unavailable row counts, and zero key-difference metrics. These checks return a single-table quality result, but the page rendered them as a two-table reconciliation result and coerced missing metrics to zero.
- History displayed `0 of 0` after standalone baseline checks. The UI had restricted verification history to quality-plan run IDs, although baseline verification creates its own run ID.
- A slow Snowflake metadata request could be mislabeled “configuration changed.” The initial request timed out before identity metadata arrived; a later read returned the configured database and 15 RAW tables.
- Minus comparison offered keys only. The two now-explicit modes are key presence across all scanned rows, or a selected column's value multiset. Neither mode silently adds a pipeline run.

## Contract and safeguards

- Reconciliation and quality results are rendered according to their actual result shape. Missing metrics display as unavailable; `PASS` is never inferred from an absent count.
- History is filtered by explicit `project_id` and `environment` **before** its limit is applied. New results carry this scope and an exact result ID. Older records without ownership metadata remain excluded; they are not deleted or reassigned.
- Row count ignores any lingering selected key. Key and column modes require explicit source and target columns. A bounded scan that hits its limit is `PARTIAL`, never a full-table pass. Column comparison retains mismatch counts, not raw compared values.
- Metadata timeout and configuration mismatch have distinct states. A failed history read does not erase an already returned comparison result or falsely claim an empty history.

## Verification and limitations

- Backend tests use disposable SQLite and fake read-only connectors; UI tests and production build exercise rendering contracts. No live comparison or pipeline was submitted during this remediation.
- On 2026-09-23, the read-only scoped UI API returned 15 PostgreSQL source tables and 15 Snowflake RAW target tables after the connector metadata completed. An initial Snowflake metadata timeout was observed and is now labeled unavailable, not a configuration change.
- Existing unscoped baseline records remain hidden because their ownership cannot be established safely. The page must not present them as belonging to the current project.
- The bounded key comparison checks presence and uniqueness of the selected key, not every non-key column's values. Column mode compares only the selected column and its multiplicity. There is no claim of a full-row equality check.
