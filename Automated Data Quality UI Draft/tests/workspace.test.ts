import assert from "node:assert/strict";
import test from "node:test";

import { canonicalAssetIdentity, nextWorkflowGeneration, projectSlug, recordMatchesCurrentActionScope, recordMatchesCurrentAnalysisScope, recordMatchesCurrentQualityScope, recordMatchesCurrentTable, workflowGeneration, workspaceQuery, workspaceRevision, type CurrentWorkspaceState } from "../lib/server-workspace.ts";
import { invalidateWorkspaceCache, normalizeWorkspaceUrl, readOnboardingBootstrap, rememberWorkspaceRevision, scopedApiUrl } from "../lib/client-workspace.ts";

test("workspace scope derives stable project identifiers", () => {
  assert.equal(projectSlug("Data Quality Testing - Beta"), "data-quality-testing-beta");
  assert.equal(projectSlug("  Finance / Revenue QA  "), "finance-revenue-qa");
});

test("workspace query encodes the selected project and environment", () => {
  assert.equal(
    workspaceQuery({ projectId: "finance qa", environment: "test/us", name: "Finance", source: "persisted_project" }),
    "project_id=finance%20qa&environment=test%2Fus",
  );
});

test("workspace revisions are scoped to project and environment and advance only from valid local state", () => {
  const finance = { projectId: "Finance QA", environment: "Test" };
  assert.equal(workflowGeneration(undefined), 0);
  assert.equal(workflowGeneration(-1), 0);
  assert.equal(nextWorkflowGeneration(undefined), 1);
  assert.equal(workspaceRevision(finance, 3), "finance-qa:test:3");
  assert.notEqual(workspaceRevision(finance, 3), workspaceRevision({ ...finance, environment: "production" }, 3));
});

function browserForWorkspaceTests(search = "?project_id=finance-qa&environment=test") {
  const values = new Map<string, string>();
  return {
    location: { search },
    sessionStorage: {
      getItem: (key: string) => values.get(key) ?? null,
      setItem: (key: string, value: string) => { values.set(key, value); },
      removeItem: (key: string) => { values.delete(key); },
    },
  };
}

test("client cache keys include the server workflow revision and can be invalidated after a clear", () => {
  const global = globalThis as unknown as { window?: unknown };
  const previousWindow = global.window;
  global.window = browserForWorkspaceTests();
  try {
    rememberWorkspaceRevision("finance-qa:test:7");
    assert.equal(scopedApiUrl("/api/onboarding?view=connections"), "/api/onboarding?view=connections&project_id=finance-qa&environment=test&workspace_revision=finance-qa%3Atest%3A7");
    invalidateWorkspaceCache();
    assert.equal(scopedApiUrl("/api/onboarding"), "/api/onboarding?project_id=finance-qa&environment=test");
  } finally {
    global.window = previousWindow;
  }
});

test("overview URL is normalized to the server-resolved project and environment", () => {
  const global = globalThis as unknown as { window?: unknown };
  const previousWindow = global.window;
  const replaced: string[] = [];
  global.window = {
    location: new URL("http://localhost:3020/?workspace_revision=data-quality-testing-beta%3Adevelopment%3A0"),
    history: { state: null, replaceState: (_state: unknown, _title: string, url: string) => replaced.push(url) },
    dispatchEvent: () => true,
  };
  try {
    normalizeWorkspaceUrl({ projectId: "data-quality-testing-beta", environment: "Development" });
    assert.deepEqual(replaced, ["http://localhost:3020/?workspace_revision=data-quality-testing-beta%3Adevelopment%3A0&project_id=data-quality-testing-beta&environment=development"]);
  } finally {
    global.window = previousWindow;
  }
});

test("bootstrap parsing distinguishes an empty saved workspace from a failed request", async () => {
  const global = globalThis as unknown as { window?: unknown };
  const previousWindow = global.window;
  global.window = browserForWorkspaceTests();
  try {
    const empty = await readOnboardingBootstrap<{ bootstrapState: string }>(new Response(JSON.stringify({ bootstrapState: "EMPTY" }), { headers: { "X-ADQ-Workspace-Revision": "finance-qa:test:8" } }));
    assert.deepEqual(empty, { kind: "empty", value: { bootstrapState: "EMPTY" }, revision: "finance-qa:test:8" });
    const failed = await readOnboardingBootstrap<Record<string, unknown>>(new Response(JSON.stringify({ bootstrapState: "ERROR", error: "state file unavailable" }), { status: 500 }));
    assert.deepEqual(failed, { kind: "error", error: "state file unavailable" });
  } finally {
    global.window = previousWindow;
  }
});

const selectedState: CurrentWorkspaceState = {
  sourceTableScopeId: "postgres:public:properties",
  analysisScopeId: "",
  qualityPlanScopeId: "",
  selectedSourceTable: { id: "postgres:public:properties", database: "", schema: "public", table: "properties" },
  selectedAssetIdentity: {
    identityVersion: 1,
    assetId: "postgres:public:properties",
    connection: "postgres",
    schema: "public",
    table: "properties",
  },
  sourceName: "postgres.public.properties",
  targetName: "raw.properties",
};

test("action plans require their persisted source scope while independent typed jobs remain accessible", () => {
  const scope = { projectId: "finance-qa", environment: "test", name: "Finance", source: "persisted_project" as const };
  const scoped = { plan_id: "plan-1", project_id: "finance-qa", environment: "test", source_table_scope_id: selectedState.sourceTableScopeId, operation_kind: "quality_checks" };
  assert.equal(recordMatchesCurrentActionScope(scoped, scope, selectedState), true);
  assert.equal(recordMatchesCurrentActionScope({ ...scoped, source_table_scope_id: "postgres:public:other" }, scope, selectedState), false);
  assert.equal(recordMatchesCurrentActionScope({ ...scoped, project_id: "another-project" }, scope, selectedState), false);
  assert.equal(recordMatchesCurrentActionScope({ ...scoped, environment: "production" }, scope, selectedState), false);
  assert.equal(recordMatchesCurrentActionScope({ ...scoped, source_table_scope_id: undefined }, scope, selectedState), false);
  assert.equal(recordMatchesCurrentActionScope({ ...scoped, source_table_scope_id: undefined, operation_kind: "dbt_execute" }, scope, selectedState), true);
  assert.equal(recordMatchesCurrentActionScope(scoped, scope, { ...selectedState, sourceTableScopeId: "" }), false);
});

test("canonical identity does not match an unrelated record with a coincidental properties field", () => {
  const unrelated = { asset_id: "postgres:public:guests", properties: "postgres.public.properties appears in a descriptive field" };
  assert.equal(recordMatchesCurrentTable(unrelated, selectedState), false);
});

test("canonical identity matches the same table and rejects schema or connection collisions", () => {
  assert.equal(recordMatchesCurrentTable({ asset_id: "postgres:public:properties", properties: { schema: "public", table: "properties", connection_id: "postgres" } }, selectedState), true);
  assert.equal(recordMatchesCurrentTable({ steps: [{ asset: "postgres.public.properties" }] }, selectedState), true);
  assert.equal(recordMatchesCurrentTable({ properties: { schema: "archive", table: "properties", connection_id: "postgres" } }, selectedState), false);
  assert.equal(recordMatchesCurrentTable({ properties: { schema: "public", table: "properties", connection_id: "snowflake" } }, selectedState), false);
});

test("missing canonical identity fails closed", () => {
  assert.equal(canonicalAssetIdentity({ name: "postgres.public.properties", description: "properties" }), null);
  assert.equal(recordMatchesCurrentTable({ name: "properties", description: "properties" }, selectedState), false);
});

test("quality plan visibility validates exact project, environment, and source scope rather than one asset identity", () => {
  const scope = { projectId: "data-quality-testing-beta", environment: "Development", name: "Beta", source: "persisted_project" as const };
  const state = { ...selectedState, sourceTableScopeId: "postgres:public:guests" };
  const plan = {
    project_id: "data-quality-testing-beta",
    environment: "development",
    source_table_scope_id: "postgres:public:guests",
    mappings: [{ source_name: "postgres.public.guests" }, { source_name: "postgres.public.loyalty_accounts" }],
  };

  assert.equal(recordMatchesCurrentQualityScope(plan, scope, state), true);
  assert.equal(recordMatchesCurrentQualityScope({ ...plan, project_id: "another-project" }, scope, state), false);
  assert.equal(recordMatchesCurrentQualityScope({ ...plan, environment: "production" }, scope, state), false);
  assert.equal(recordMatchesCurrentQualityScope({ ...plan, source_table_scope_id: "postgres:public:booking_channels" }, scope, state), false);
  assert.equal(recordMatchesCurrentQualityScope({ project_id: scope.projectId, environment: scope.environment }, scope, state), false);
});

test("analysis visibility requires exact project, environment, and active source-table scope", () => {
  const scope = { projectId: "data-quality-testing-beta", environment: "Development", name: "Beta", source: "persisted_project" as const };
  const state = { ...selectedState, sourceTableScopeId: "postgres:public:guests" };
  const analysis = { project_id: scope.projectId, environment: "development", source_table_scope_id: "postgres:public:guests" };

  assert.equal(recordMatchesCurrentAnalysisScope(analysis, scope, state), true);
  assert.equal(recordMatchesCurrentAnalysisScope({ ...analysis, source_table_scope_id: "postgres:public:booking_channels" }, scope, state), false);
  assert.equal(recordMatchesCurrentAnalysisScope({ ...analysis, environment: "production" }, scope, state), false);
  assert.equal(recordMatchesCurrentAnalysisScope({ ...analysis, project_id: "another-project" }, scope, state), false);
  assert.equal(recordMatchesCurrentAnalysisScope({ project_id: scope.projectId, environment: scope.environment }, scope, state), false);
});
