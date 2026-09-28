import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import test from "node:test";

import { matchesCurrentQualityPlan, qualityRunsForPlan, qualityRunsForTable } from "../lib/operations-quality-scope.ts";
import type { CurrentWorkspaceState, WorkspaceScope } from "../lib/server-workspace.ts";

const scope: WorkspaceScope = {
  projectId: "data-quality-testing-beta",
  environment: "development",
  name: "Data Quality Testing - Beta",
  source: "persisted_project",
};

const state: CurrentWorkspaceState = {
  sourceTableScopeId: "postgres:public:guests",
  analysisScopeId: "postgres:public:guests",
  qualityPlanScopeId: "postgres:public:guests",
  selectedSourceTable: { id: "postgres:public:guests", schema: "public", table: "guests" },
  selectedAssetIdentity: { identityVersion: 1, assetId: "postgres:public:guests", connection: "postgres", schema: "public", table: "guests" },
  sourceName: "postgres.public.guests",
  targetName: "raw.guests",
};

test("overview accepts the Rules API plan for the exact project, environment, and selected table", () => {
  const plan = { plan_id: "quality_plan_current", project_id: "DATA-QUALITY-TESTING-BETA", environment: "Development", source_table_scope_id: "postgres:public:guests", status: "DRAFT", summary: { check_count: 16, review_required_count: 13 } };
  assert.equal(matchesCurrentQualityPlan(plan, scope, state), true);
});

test("overview rejects a plan for another project, environment, table, or an unbound legacy plan", () => {
  const plan = { project_id: scope.projectId, environment: scope.environment, source_table_scope_id: state.sourceTableScopeId };
  assert.equal(matchesCurrentQualityPlan({ ...plan, project_id: "another-project" }, scope, state), false);
  assert.equal(matchesCurrentQualityPlan({ ...plan, environment: "production" }, scope, state), false);
  assert.equal(matchesCurrentQualityPlan({ ...plan, source_table_scope_id: "postgres:public:payments" }, scope, state), false);
  assert.equal(matchesCurrentQualityPlan({ project_id: scope.projectId, environment: scope.environment }, scope, state), false);
  assert.equal(matchesCurrentQualityPlan(plan, scope, { ...state, sourceTableScopeId: "", selectedSourceTable: null }), false);
});

test("table history includes exact scoped runs across revisions and excludes other or unscoped history", () => {
  const history = [
    { run_id: "current-plan-run", plan_id: "quality_plan_current", plan_revision: 1, source_table_scope_id: "postgres:public:guests" },
    { run_id: "prior-plan-run", plan_id: "quality_plan_previous", plan_revision: 2, source_table_scope_id: "postgres:public:guests" },
    { run_id: "other-table-run", plan_id: "quality_plan_other", source_table_scope_id: "postgres:public:payments" },
    { run_id: "legacy-unscoped-run", plan_id: "quality_plan_legacy" },
  ];
  assert.deepEqual(qualityRunsForTable(history, state.sourceTableScopeId).map((run) => run.run_id), ["current-plan-run", "prior-plan-run"]);
  assert.equal(qualityRunsForTable(history, "").length, 0);
});

test("current-plan executions stay separate from cross-revision history", () => {
  const history = [
    { run_id: "current-plan-run", plan_id: "quality_plan_current", plan_revision: 1 },
    { run_id: "prior-plan-run", plan_id: "quality_plan_previous", plan_revision: 2 },
  ];
  assert.deepEqual(qualityRunsForPlan(history, "quality_plan_current").map((run) => run.run_id), ["current-plan-run"]);
  assert.deepEqual(qualityRunsForTable(history.map((run) => ({ ...run, source_table_scope_id: state.sourceTableScopeId })), state.sourceTableScopeId).map((run) => run.run_id), ["current-plan-run", "prior-plan-run"]);
});

test("Overview route and page use explicit plan and cross-revision history states", async () => {
  const [route, page] = await Promise.all([
    readFile(new URL("../app/api/operations/route.ts", import.meta.url), "utf8"),
    readFile(new URL("../app/page.tsx", import.meta.url), "utf8"),
  ]);
  assert.match(route, /matchesCurrentQualityPlan\(candidatePlan, scope, state\)/);
  assert.match(route, /\/api\/v1\/quality-runs\?/);
  assert.match(route, /qualityRunsForPlan\(/);
  const planResolver = route.slice(route.indexOf("async function qualityPlanState"), route.indexOf("async function persistedOverview"));
  assert.match(planResolver, /quality-plans\/latest/);
  assert.doesNotMatch(planResolver, /if\s*\(!hasEvidence\)/, "an exact-scope persisted plan must not depend on onboarding progress markers");
  assert.match(page, /Saved runs across revisions/);
  assert.match(page, /No run on this plan revision/);
  assert.doesNotMatch(page, /data\?\.plan\.status \?\? "NOT GENERATED"/);
});
