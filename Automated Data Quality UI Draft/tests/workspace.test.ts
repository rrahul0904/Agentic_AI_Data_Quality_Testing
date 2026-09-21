import assert from "node:assert/strict";
import test from "node:test";

import { canonicalAssetIdentity, projectSlug, recordMatchesCurrentTable, workspaceQuery, type CurrentWorkspaceState } from "../lib/server-workspace.ts";

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
