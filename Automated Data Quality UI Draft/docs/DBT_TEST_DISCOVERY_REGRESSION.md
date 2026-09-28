# dbt quality-test discovery regression

## Finding

When onboarding a selected PostgreSQL source table, the dbt manifest traversal
followed dependency edges but returned only `model` resource IDs. dbt `test`
resources were therefore removed by the selected-table discovery filter before
the result was persisted. Catalog and Lineage consequently showed no quality
checks even though the manifest contained tests attached to the selected
table's models.

## Fix

Selected-table dbt discovery now retains both reachable model and test
resources. Matching remains based on one exact `raw` dbt source identity in an
allowed target database and the manifest's explicit dependency edges; ambiguous
or missing sources still fail closed. The onboarding workflow reports models
and defined tests separately. Tests appear in Catalog's `Quality / other` layer
and can be grouped in Lineage.

Discovery of a dbt test is a definition only. It must remain `NOT RUN` until
there is a real execution record; this change does not execute dbt or imply a
pass/fail result.

The local manifest currently resolves the selected `raw.guests` source to 10
models and 34 tests in the transitive downstream dependency closure. The 34
tests include checks attached to shared downstream models, so this is an
impact-scope count—not a claim that every test is exclusively about guest
records.

## Regression coverage

`tests/onboarding.test.ts` verifies that a source returns its transitive models
and associated tests, excludes similarly named but unrelated source/test
resources, and returns no matches for a missing, ambiguous, or unconfigured
source. The real local manifest was also evaluated through the same helper on
September 22, 2026: 10 models and 34 dependency-related tests were returned for
`raw.guests`; no execution was performed.

## Refreshing an existing workspace

Previously saved per-table discovery is not silently rewritten. For an
existing project, rerun **Run workflow for this table** for each selected
source, then rerun **Run automated analysis** to persist the newly discovered
test definitions in Catalog and Lineage. New dbt discovery records carry a
discovery contract version. Older passing records are now labeled “Refresh
required” rather than reporting `0 related tests` as if the complete test
inventory had been checked. No pipeline or quality test is run by these
refresh actions.

## Scope-isolation regression

Catalog and Lineage now verify that a returned analysis explicitly matches the
active project, environment, and source-table scope. A mismatched or
unscoped backend `latest` response is hidden with an actionable warning; an
analysis or runtime-refresh response for another scope is not marked current.
Regression tests cover exact matches and project, environment, table, and
missing-scope mismatches.
