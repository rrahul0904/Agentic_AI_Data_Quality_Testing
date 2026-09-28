# Approved plan blocks custom rule creation

## Finding

On Quality rules, **Create draft rule** was disabled whenever the current plan
had status `APPROVED`. This prevented an operator from adding a new rule even
though the quality-plan update API accepts `add_checks` on an approved plan.

## Correct contract

- An operator may add a rule tied to an evidence-supported mapping.
- Saving creates a new `DRAFT` revision and clears the prior approval; it does
  not edit the previously approved revision in place.
- The added rule starts disabled and requiring review. Nothing executes merely
  because the draft was created.
- Execution remains blocked until the new revision is explicitly approved.

## Regression coverage

- `tests/phase3-ui-clarity.test.ts` checks that the authoring control is usable
  on an approved plan and sends the selected mapping ID.
- Backend `tests/test_quality_plans.py` verifies the approved-to-draft
  transition, preserved revision history, disabled new rule, and execution
  rejection before reapproval.
- Browser verification on the production build confirmed the control is enabled
  with the existing approved guests plan. No rule was submitted during that
  check, so the approved application data was unchanged.
