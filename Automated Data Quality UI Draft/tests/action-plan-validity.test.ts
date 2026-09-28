import assert from "node:assert/strict";
import test from "node:test";
import { isIncompleteEndToEnd } from "../lib/action-plan-validity.ts";

test("legacy one-DAG end-to-end preview cannot retain an approval path", () => {
  assert.equal(isIncompleteEndToEnd({ mode: "end_to_end", steps: [{ kind: "airflow_trigger" }] }), true);
  assert.equal(isIncompleteEndToEnd({ mode: "single_job", steps: [{ kind: "airflow_trigger" }] }), false);
  assert.equal(isIncompleteEndToEnd({ mode: "end_to_end", steps: [{ kind: "airflow_trigger" }, { kind: "dbt_execute" }] }), false);
  assert.equal(isIncompleteEndToEnd(null), false);
});
