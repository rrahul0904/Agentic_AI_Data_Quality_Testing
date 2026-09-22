import assert from "node:assert/strict";
import test from "node:test";

import { recordMatchesCurrentExecution, recordMatchesCurrentTable, type CurrentWorkspaceState } from "../lib/server-workspace.ts";

const bookingChannelsState: CurrentWorkspaceState = {
  sourceTableScopeId: "postgres:public:booking_channels",
  analysisScopeId: "postgres:public:booking_channels",
  qualityPlanScopeId: "postgres:public:booking_channels",
  selectedSourceTable: { id: "postgres:public:booking_channels", database: "", schema: "public", table: "booking_channels" },
  selectedAssetIdentity: {
    identityVersion: 1,
    assetId: "postgres:public:booking_channels",
    connection: "postgres",
    schema: "public",
    table: "booking_channels",
  },
  sourceName: "postgres.public.booking_channels",
  targetName: "raw.booking_channels",
};

test("current selected booking_channels state excludes historical and unrelated assets", () => {
  assert.equal(recordMatchesCurrentTable({ asset_id: "postgres:public:booking_channels" }, bookingChannelsState), true);
  assert.equal(recordMatchesCurrentTable({ asset_id: "postgres:public:booking_channels_history" }, bookingChannelsState), false);
  assert.equal(recordMatchesCurrentTable({ properties: { schema: "archive", table: "booking_channels", connection_id: "postgres" } }, bookingChannelsState), false);

  const current = { asset_id: "postgres:public:booking_channels", run_id: "run-current" };
  assert.equal(recordMatchesCurrentExecution(current, bookingChannelsState, new Set(["run-current"])), true);
  assert.equal(recordMatchesCurrentExecution({ ...current, run_id: "run-historical" }, bookingChannelsState, new Set(["run-current"])), false);
});

test("empty or stale current scope fails closed even when historical run ids exist", () => {
  const cleared = { ...bookingChannelsState, sourceTableScopeId: "", analysisScopeId: "", qualityPlanScopeId: "", selectedAssetIdentity: null };
  assert.equal(recordMatchesCurrentExecution({ asset_id: "postgres:public:booking_channels", run_id: "run-historical" }, cleared, new Set(["run-historical"])), false);
  assert.equal(recordMatchesCurrentExecution({ asset_id: "postgres:public:booking_channels", run_id: "run-current" }, bookingChannelsState, new Set()), false);
});
