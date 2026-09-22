import assert from "node:assert/strict";
import test from "node:test";
import { assetsForSourceTable, discoveriesForSourceTable, selectedAssetsForScope } from "../lib/discovery-scope.ts";

const result = (sourceTableId: string, assets: Array<{ id: string; name: string }>) => ({
  status: "PASS" as const,
  detail: "observed",
  source: "fixture",
  discoveredAt: "2026-09-22T00:00:00Z",
  sourceTableId,
  assets: assets.map((asset) => ({
    ...asset,
    connectionId: "runtime-postgres",
    type: "BASE TABLE",
  })),
});

test("current discovery uses only the active source-table scope", () => {
  const byTable = {
    "postgres:public:room_types": { postgres: result("postgres:public:room_types", [{ id: "room", name: "room_types" }]) },
    "postgres:public:stays": { postgres: result("postgres:public:stays", [{ id: "stays", name: "stays" }]) },
  };

  assert.deepEqual(Object.keys(discoveriesForSourceTable("postgres:public:room_types", byTable, {})), ["postgres"]);
  assert.deepEqual(assetsForSourceTable("postgres:public:room_types", byTable, {}).map((asset) => asset.id), ["room"]);
  assert.deepEqual(assetsForSourceTable("postgres:public:stays", byTable, {}).map((asset) => asset.id), ["stays"]);
  assert.deepEqual(assetsForSourceTable(undefined, byTable, {}).map((asset) => asset.id), []);
});

test("unscoped legacy discoveries are not used as current assets", () => {
  const legacy = {
    old: result("postgres:public:booking_channels", [{ id: "old", name: "booking_channels" }]),
    current: result("postgres:public:room_types", [{ id: "current", name: "room_types" }]),
  };
  assert.deepEqual(assetsForSourceTable("postgres:public:room_types", {}, legacy).map((asset) => asset.id), ["current"]);
  assert.deepEqual(assetsForSourceTable("postgres:public:stays", {}, legacy), []);
});

test("selected assets are limited to assets observed in the active scope", () => {
  const scoped = [{ id: "room", connectionId: "runtime-postgres", name: "room_types", type: "BASE TABLE" }];
  assert.deepEqual(selectedAssetsForScope(["old", "room"], scoped), ["room"]);
});
