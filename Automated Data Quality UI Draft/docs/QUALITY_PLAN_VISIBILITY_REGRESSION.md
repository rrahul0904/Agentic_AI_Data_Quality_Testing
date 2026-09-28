# Quality plan visibility regression

## Finding

The quality-plan endpoint returned `NO PLAN` even though the backend had
generated a draft. The UI applied an asset-identity matcher to the plan
envelope. Plans are not individual assets: they carry exact project,
environment, and source-table-scope identifiers and can contain mappings for
multiple explicitly selected source tables. The mismatch hid the generated
plan while the UI still showed a successful-generation notice.

## Fix

Plan reads now require exact project ID, environment, and source-table scope
matches. This is a narrow plan-specific check; the stricter canonical asset
matcher used for individual assets and evidence is unchanged. If generation
returns successfully but the scoped read-back cannot load that plan, the UI
shows an error rather than a success notice.

## Regression coverage

`tests/workspace.test.ts` verifies that an exactly scoped multi-mapping plan
is visible, while another project, environment, source scope, or a missing
scope is rejected.

## Current workspace evidence

On September 22, 2026, the backend returned a saved draft for
`data-quality-testing-beta / development / postgres:public:guests` with 2
mappings and 31 recommended checks. It was not executed. The prior UI hid that
draft because it lacked an asset identity at the top level.
